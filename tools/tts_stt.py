"""TTS/STT tools — text-to-speech and speech-to-text integration."""
import base64
import json
import os
import re
import tempfile
from pathlib import Path
from tools.registry import ToolRegistry


# ===== TTS 文本清洗 =====

# Emoji 正则
_EMOJI_PATTERN = re.compile(
    "["
    "\U0001F600-\U0001F64F"  # emoticons
    "\U0001F300-\U0001F5FF"  # symbols & pictographs
    "\U0001F680-\U0001F6FF"  # transport & map symbols
    "\U0001F1E0-\U0001F1FF"  # flags
    "\U00002700-\U000027BF"  # dingbats
    "\U0001F900-\U0001F9FF"  # supplemental symbols
    "\U00002600-\U000026FF"  # misc symbols
    "\U0001FA00-\U0001FA6F"  # chess symbols
    "\U0001FA70-\U0001FAFF"  # extended symbols
    "\U00002B00-\U00002BFF"  # arrows
    "]+",
    flags=re.UNICODE,
)


def clean_text_for_tts(text: str) -> str:
    """清洗文本用于 TTS：去除 Markdown 符号、emoji、代码块、URL 等。"""
    if not text:
        return ""

    # 去除代码块
    text = re.sub(r"```[\s\S]*?```", "", text)
    # 去除行内代码
    text = re.sub(r"`[^`]+`", "", text)
    # 去除标题标记
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    # 去除粗体/斜体标记
    text = re.sub(r"\*{1,3}([^*]+)\*{1,3}", r"\1", text)
    text = re.sub(r"_{1,3}([^_]+)_{1,3}", r"\1", text)
    # 去除删除线
    text = re.sub(r"~~([^~]+)~~", r"\1", text)
    # 去除链接 [text](url) -> text
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    # 去除图片
    text = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", text)
    # 去除 URL
    text = re.sub(r"https?://\S+", "", text)
    # 去除引用标记
    text = re.sub(r"^>\s+", "", text, flags=re.MULTILINE)
    # 去除水平分割线
    text = re.sub(r"^[\-\*_]{3,}$", "", text, flags=re.MULTILINE)
    # 去除列表标记
    text = re.sub(r"^\s*[\-\*\+]\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*\d+\.\s+", "", text, flags=re.MULTILINE)
    # 去除表格分隔符
    text = re.sub(r"^\|[\s\-\|:]+\|$", "", text, flags=re.MULTILINE)
    # 去除表格竖线
    text = re.sub(r"\|", " ", text)
    # 去除 emoji
    text = _EMOJI_PATTERN.sub("", text)
    # 去除其他不可读符号
    text = re.sub(r"[#~`>_]", "", text)
    # 合并多余空格和换行
    text = re.sub(r"\s+", " ", text)
    text = text.strip()

    return text


def handle_tts_synthesize(**kwargs):
    """Convert text to speech audio using MiMo TTS or Edge TTS.

    Supports automatic fallback: if MiMo TTS fails (balance, network, etc.),
    automatically falls back to Edge TTS (free, no API key needed).

    Args:
        text: Text to synthesize
        voice: Voice name (e.g., 'mimo_default', '冰糖', '茉莉', '苏打', '白桦')
        style: Speaking style instruction (Chinese recommended for better effect)
        provider: TTS provider ('auto', 'mimo', or 'edge'). 'auto' tries MiMo first.
        rate: Speech rate for Edge TTS (e.g., '+8%')
        pitch: Pitch for Edge TTS (e.g., '+2Hz')
    """
    text = kwargs.get("text", "")
    voice = kwargs.get("voice", "mimo_default")
    style = kwargs.get("style", "")
    rate = kwargs.get("rate", "+8%")
    pitch = kwargs.get("pitch", "+2Hz")

    # Default to 'auto' which tries MiMo first, then Edge TTS
    try:
        from core.user_config import get_tts_config
        default_provider = get_tts_config().get("default_provider", "auto")
    except Exception:
        default_provider = "auto"
    provider = kwargs.get("provider", default_provider)

    if not text.strip():
        return {"error": "Text is empty"}

    # Clean text for TTS
    clean = clean_text_for_tts(text)
    if not clean:
        return {"error": "Text is empty after cleaning"}

    if provider == "mimo":
        result = _synthesize_mimo(clean, voice, style)
        if "error" in result:
            print(f"[TTS] MiMo failed: {result['error']}, falling back to Edge TTS")
            return _synthesize_edge(clean, voice, rate, pitch)
        return result
    elif provider == "auto":
        # Try MiMo first if API key is configured
        mimo_key = os.getenv("MIMO_TTS_API_KEY", "")
        try:
            from core.user_config import get_tts_config
            mimo_key = get_tts_config().get("mimo_api_key", "") or mimo_key
        except Exception:
            pass

        if mimo_key:
            result = _synthesize_mimo(clean, voice, style)
            if "success" in result:
                return result
            print(f"[TTS] MiMo fallback: {result.get('error', 'unknown')}")
        # Fall back to Edge TTS
        return _synthesize_edge(clean, voice, rate, pitch)
    elif provider == "edge":
        return _synthesize_edge(clean, voice, rate, pitch)
    else:
        return {"error": f"Unknown provider: {provider}. Use 'auto', 'mimo' or 'edge'"}

def _synthesize_mimo(text: str, voice: str, style: str) -> dict:
    """Synthesize using MiMo TTS API via chat/completions endpoint.

    MiMo TTS 独特调用格式：
    - assistant 角色的消息包含要合成的文本
    - user 角色的消息传递风格/情绪指令
    - voice 必须使用 MiMo 专属音色名: mimo_default, 冰糖, 茉莉, 苏打, 白桦, Mia, Chloe, Milo, Dean
    """
    import requests
    import base64
    import uuid

    # Check user config first, then env
    try:
        from core.user_config import get_tts_config
        tts_cfg = get_tts_config()
        api_key = tts_cfg.get("mimo_api_key", "") or os.getenv("MIMO_TTS_API_KEY", "")
    except Exception:
        api_key = os.getenv("MIMO_TTS_API_KEY", "")
    if not api_key:
        return {"error": "MiMo TTS API key not configured. Set MIMO_TTS_API_KEY in .env"}

    # Text is already cleaned by handle_tts_synthesize, use directly
    clean = text
    if not clean:
        return {"error": "Text is empty after cleaning"}

    # 验证 voice 名称 - 只允许 MiMo 支持的音色
    valid_voices = ["mimo_default", "冰糖", "茉莉", "苏打", "白桦", "Mia", "Chloe", "Milo", "Dean"]
    if voice not in valid_voices:
        voice = "mimo_default"  # 默认使用 mimo_default

    # Base style instruction — 仿真人对话风格
    base_style = "用日常聊天的语速快速说话，像真人朋友之间聊天，不要字正腔圆，不要播音腔，自然随意一点，带一点情绪起伏。"
    full_style = f"{base_style} {style}".strip() if style else base_style

    # MiMo TTS 调用格式：
    # - user 消息: 风格指令
    # - assistant 消息: 要合成的文本
    # - modalities: ["audio"]
    # - audio: {"voice": voice, "format": "mp3"}
    payload = {
        "model": "mimo-v2.5-tts",
        "messages": [
            {"role": "user", "content": full_style},
            {"role": "assistant", "content": clean},
        ],
        "modalities": ["audio"],
        "audio": {"voice": voice, "format": "mp3"},
    }

    try:
        response = requests.post(
            "https://api.xiaomimimo.com/v1/chat/completions",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            json=payload,
            timeout=30,
        )

        # 如果余额不足或其他错误，返回错误信息（上层会自动回退到 Edge TTS）
        if response.status_code == 402:
            return {"error": "MiMo account balance insufficient (402). Falling back to Edge TTS."}
        if response.status_code == 404:
            return {"error": "MiMo TTS endpoint not found (404). Falling back to Edge TTS."}
        if response.status_code == 400:
            err_msg = response.text[:300]
            return {"error": f"MiMo TTS bad request (400): {err_msg}. Falling back to Edge TTS."}

        response.raise_for_status()

        result = response.json()

        # 从 choices 中提取音频数据
        # MiMo TTS 返回格式: choices[0].message.audio.data (base64)
        if "choices" in result and len(result["choices"]) > 0:
            choice = result["choices"][0]
            message = choice.get("message", {})

            # 尝试多种音频数据路径
            audio_data = ""
            if "audio" in message:
                audio_data = message["audio"].get("data", "") or message["audio"].get("base64", "")
            elif "audio" in choice:
                audio_data = choice["audio"].get("data", "") or choice["audio"].get("base64", "")

            if audio_data:
                output_dir = os.path.join(os.getenv("AGENT_HOME", "/opt/agent-framework"), "data", "audio")
                os.makedirs(output_dir, exist_ok=True)

                filename = f"tts_{uuid.uuid4().hex[:8]}.mp3"
                filepath = os.path.join(output_dir, filename)

                audio_bytes = base64.b64decode(audio_data)
                with open(filepath, "wb") as f:
                    f.write(audio_bytes)

                return {
                    "success": True,
                    "filepath": filepath,
                    "filename": filename,
                    "voice": voice,
                    "text_length": len(clean),
                    "provider": "mimo",
                }
            else:
                return {"error": "No audio data in MiMo response", "raw_keys": list(message.keys())}
        else:
            return {"error": "Unexpected MiMo response format", "raw": str(result)[:200]}

    except requests.exceptions.Timeout:
        return {"error": "MiMo TTS request timeout. Falling back to Edge TTS."}
    except Exception as e:
        return {"error": f"MiMo TTS error: {str(e)}. Falling back to Edge TTS."}


# 全局线程池复用，避免每次创建新线程
_edge_tts_executor = None

def _get_edge_tts_executor():
    global _edge_tts_executor
    if _edge_tts_executor is None:
        import concurrent.futures
        _edge_tts_executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)
    return _edge_tts_executor

def _synthesize_edge(text: str, voice: str, rate: str = "+8%", pitch: str = "+2Hz") -> dict:
    """Synthesize using Edge TTS with natural voice parameters.

    rate: 语速调整 (默认+8% 更接近真人对话节奏)
    pitch: 音调调整 (默认+2Hz 更有活力)
    """
    try:
        import edge_tts
        import asyncio

        # Text is already cleaned by handle_tts_synthesize, use directly
        clean_text = text
        if not clean_text:
            return {"error": "Text is empty after cleaning"}

        output_dir = os.path.join(os.getenv("AGENT_HOME", "/opt/agent-framework"), "data", "audio")
        os.makedirs(output_dir, exist_ok=True)

        import uuid
        filename = f"tts_{uuid.uuid4().hex[:8]}.mp3"
        filepath = os.path.join(output_dir, filename)

        # Map voice names
        voice_map = {
            "mimo_default": "zh-CN-XiaoxiaoNeural",
            "female_cn": "zh-CN-XiaoxiaoNeural",
            "male_cn": "zh-CN-YunxiNeural",
            "female_en": "en-US-JennyNeural",
            "male_en": "en-US-GuyNeural",
        }
        edge_voice = voice_map.get(voice, voice)

        async def _synthesize():
            communicate = edge_tts.Communicate(
                clean_text, edge_voice,
                rate=rate,
                pitch=pitch,
                volume="+0%",
            )
            await communicate.save(filepath)

        # 复用全局线程池，避免每次创建新线程
        def _run_async():
            import asyncio as _asyncio
            loop = _asyncio.new_event_loop()
            _asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(_synthesize())
            finally:
                loop.close()

        executor = _get_edge_tts_executor()
        future = executor.submit(_run_async)
        future.result(timeout=15)

        return {
            "success": True,
            "filepath": filepath,
            "filename": filename,
            "voice": edge_voice,
            "text_length": len(clean_text),
            "original_length": len(text),
            "cleaned_text": clean_text[:100],
            "provider": "edge",
            "rate": rate,
            "pitch": pitch,
        }

    except ImportError:
        return {"error": "edge-tts not installed. Run: pip install edge-tts"}
    except Exception as e:
        return {"error": str(e)}


def handle_stt_transcribe(**kwargs):
    """Transcribe audio to text using speech recognition.

    Args:
        audio_file: Path to audio file (mp3, wav, m4a, etc.)
        language: Language code (default: 'zh' for Chinese)
        provider: STT provider ('whisper' or 'google')
    """
    audio_file = kwargs.get("audio_file", "")
    language = kwargs.get("language", "zh")
    provider = kwargs.get("provider", "local")

    # 本地引擎优先：随框架自带、无需密钥、音频不出服务器
    if provider in ("local", "faster-whisper", "whisper_local"):
        try:
            from tools import stt_local
            if stt_local.is_available():
                r = stt_local.transcribe(audio_file, language)
                if r.get("ok"):
                    return r
        except Exception:
            pass
        provider = "whisper"  # 本地不可用则回落云端

    if not audio_file:
        return {"error": "Audio file path required"}

    if not os.path.exists(audio_file):
        return {"error": f"Audio file not found: {audio_file}"}

    if provider == "whisper":
        return _transcribe_whisper(audio_file, language)
    elif provider == "google":
        return _transcribe_google(audio_file, language)
    else:
        return {"error": f"Unknown provider: {provider}. Use 'whisper' or 'google'"}


def _transcribe_whisper(audio_file: str, language: str) -> dict:
    """Transcribe using OpenAI Whisper API or local Whisper model."""
    # Try using StepFun's Whisper-compatible endpoint first
    api_key = os.getenv("STEPFUN_API_KEY", "")

    if api_key:
        import requests

        try:
            with open(audio_file, "rb") as f:
                files = {"file": (os.path.basename(audio_file), f, "audio/mpeg")}
                data = {"model": "whisper-1", "language": language, "response_format": "json"}

                response = requests.post(
                    "https://api.stepfun.com/v1/audio/transcriptions",
                    headers={"Authorization": f"Bearer {api_key}"},
                    files=files,
                    data=data,
                    timeout=120,
                )
                response.raise_for_status()

                result = response.json()
                text = result.get("text", "")

                return {
                    "success": True,
                    "text": text,
                    "language": language,
                    "provider": "stepfun_whisper",
                    "audio_file": audio_file,
                }

        except Exception as e:
            # Fall back to local Whisper
            pass

    # Try local Whisper
    try:
        import whisper

        model = whisper.load_model("base")
        result = model.transcribe(audio_file, language=language)

        return {
            "success": True,
            "text": result.get("text", ""),
            "language": language,
            "provider": "local_whisper",
            "audio_file": audio_file,
        }

    except ImportError:
        return {"error": "Whisper not available. Install openai-whisper or configure StepFun API key."}
    except Exception as e:
        return {"error": str(e)}


def _transcribe_google(audio_file: str, language: str) -> dict:
    """Transcribe using Google Speech Recognition (free, requires internet)."""
    try:
        import speech_recognition as sr

        recognizer = sr.Recognizer()

        with sr.AudioFile(audio_file) as source:
            audio = recognizer.record(source)

        # Map language codes
        lang_map = {"zh": "zh-CN", "en": "en-US", "ja": "ja-JP"}
        google_lang = lang_map.get(language, language)

        text = recognizer.recognize_google(audio, language=google_lang)

        return {
            "success": True,
            "text": text,
            "language": language,
            "provider": "google",
            "audio_file": audio_file,
        }

    except ImportError:
        return {"error": "SpeechRecognition not installed. Run: pip install SpeechRecognition"}
    except Exception as e:
        return {"error": str(e)}


def handle_tts_list_voices(**kwargs):
    """List available TTS voices and providers."""
    voices = {
        "mimo": {
            "provider": "MiMo TTS (小米)",
            "voices": [
                {"id": "mimo_default", "name": "默认", "gender": "neutral"},
                {"id": "冰糖", "name": "冰糖", "gender": "female"},
                {"id": "茉莉", "name": "茉莉", "gender": "female"},
                {"id": "苏打", "name": "苏打", "gender": "male"},
                {"id": "白桦", "name": "白桦", "gender": "male"},
                {"id": "Mia", "name": "Mia", "gender": "female", "language": "en"},
                {"id": "Chloe", "name": "Chloe", "gender": "female", "language": "en"},
                {"id": "Milo", "name": "Milo", "gender": "male", "language": "en"},
                {"id": "Dean", "name": "Dean", "gender": "male", "language": "en"},
            ],
            "requires_api_key": True,
        },
        "edge": {
            "provider": "Edge TTS (Microsoft, 免费)",
            "voices": [
                {"id": "zh-CN-XiaoxiaoNeural", "name": "晓晓", "gender": "female", "language": "zh"},
                {"id": "zh-CN-YunxiNeural", "name": "云希", "gender": "male", "language": "zh"},
                {"id": "en-US-JennyNeural", "name": "Jenny", "gender": "female", "language": "en"},
                {"id": "en-US-GuyNeural", "name": "Guy", "gender": "male", "language": "en"},
            ],
            "requires_api_key": False,
        },
    }

    return {"providers": voices}


def register(registry: ToolRegistry):
    """Register TTS/STT tools."""
    registry.register(
        name="tts_synthesize",
        description="将文本转换为语音音频。支持MiMo TTS（高质量中文）和Edge TTS（免费）。返回音频文件路径。",
        handler=handle_tts_synthesize,
        toolset="tts_stt",
        parameters={
            "text": {"type": "string", "description": "要转换的文本", "required": True},
            "voice": {"type": "string", "description": "语音名称（默认mimo_default）", "required": False},
            "style": {"type": "string", "description": "说话风格指令（建议中文）", "required": False},
            "provider": {"type": "string", "description": "TTS提供商（mimo或edge）", "required": False},
            "rate": {"type": "string", "description": "语速调整（如+8%）", "required": False},
            "pitch": {"type": "string", "description": "音调调整（如+2Hz）", "required": False},
        },
    )

    registry.register(
        name="stt_transcribe",
        description="将音频文件转录为文本。支持Whisper（高精度）和Google语音识别（免费）。",
        handler=handle_stt_transcribe,
        toolset="tts_stt",
        parameters={
            "audio_file": {"type": "string", "description": "音频文件路径", "required": True},
            "language": {"type": "string", "description": "语言代码（默认zh）", "required": False},
            "provider": {"type": "string", "description": "STT提供商（whisper或google）", "required": False},
        },
    )

    registry.register(
        name="tts_list_voices",
        description="列出所有可用的TTS语音和提供商。",
        handler=handle_tts_list_voices,
        toolset="tts_stt",
        parameters={},
    )
