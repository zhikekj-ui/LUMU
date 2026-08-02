"""LUMU 本地语音识别（faster-whisper, CPU int8）。

设计原则：
- 随框架自带：pip 依赖 + 首次自动下载模型，不依赖任何外部密钥/第三方服务。
- 隐私优先：音频只在本机 ffmpeg 转码 + 本机推理，不出服务器。
- 懒加载单例：首次调用加载模型（约 1-3 秒），之后常驻内存复用。

环境变量：
- LUMU_STT_MODEL: 模型规格（tiny/base/small/medium），默认 base
- HF_ENDPOINT:    模型下载源，默认 https://hf-mirror.com（直连 HF 不通时的镜像）
"""
import os
from pathlib import Path
import logging
import tempfile
import threading
import subprocess

logger = logging.getLogger("lumu")

AGENT_HOME = os.getenv("AGENT_HOME", str(Path(__file__).resolve().parent.parent))
MODEL_DIR = os.path.join(AGENT_HOME, "data", "models")
MODEL_SIZE = os.getenv("LUMU_STT_MODEL", "small")  # small: 中文准确度显著优于 base

_model = None
_lock = threading.Lock()


def _resolve_model_ref() -> str:
    """优先用本地已下载的模型目录（离线可用、不依赖 HF 网络）；否则回落到规格名自动下载。"""
    explicit = os.getenv("LUMU_STT_MODEL_PATH", "").strip()
    if explicit and os.path.isfile(os.path.join(explicit, "model.bin")):
        return explicit
    for size in [MODEL_SIZE, "small", "base", "tiny"]:
        d = os.path.join(MODEL_DIR, f"faster-whisper-{size}")
        if os.path.isfile(os.path.join(d, "model.bin")):
            return d
    return MODEL_SIZE


def is_available() -> bool:
    try:
        import faster_whisper  # noqa: F401
    except Exception:
        return False
    ref = _resolve_model_ref()
    # 本地目录已就绪，或允许联网自动下载
    return os.path.isdir(ref) or True


def model_ready() -> bool:
    """模型权重是否已在本地（无需联网）。"""
    return os.path.isdir(_resolve_model_ref())


def _ensure_model():
    global _model
    if _model is None:
        with _lock:
            if _model is None:
                os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
                from faster_whisper import WhisperModel
                ref = _resolve_model_ref()
                logger.info("STT: loading faster-whisper model=%s ...", ref)
                _model = WhisperModel(
                    ref, device="cpu", compute_type="int8",
                    download_root=MODEL_DIR, num_workers=1, cpu_threads=4,
                )
                logger.info("STT: model ready (%s)", ref)
    return _model


def to_wav16k(src: str) -> str:
    """任意音频（webm/opus、m4a、mp3…）→ 16k 单声道 wav。"""
    fd, dst = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    subprocess.run(
        ["ffmpeg", "-y", "-i", src, "-ar", "16000", "-ac", "1", "-f", "wav", dst],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120, check=True,
    )
    return dst


def transcribe(path: str, language: str = "zh") -> dict:
    """转录音频为文本。返回 {ok, text, provider, language, duration} 或 {ok:False, error}。"""
    wav = None
    try:
        if not os.path.isfile(path):
            return {"ok": False, "error": f"音频文件不存在: {path}"}
        try:
            wav = to_wav16k(path)
        except Exception as e:
            return {"ok": False, "error": f"音频转码失败（ffmpeg）: {e}"}

        model = _ensure_model()
        lang = (language or "").strip() or None
        kw = dict(language=lang, beam_size=1, task="transcribe",
                  condition_on_previous_text=False,
                  initial_prompt="以下是普通话对话内容。")
        try:
            segments, info = model.transcribe(
                wav, vad_filter=True,
                vad_parameters=dict(min_silence_duration_ms=400), **kw)
            text = "".join(s.text for s in segments).strip()
        except Exception as e:
            logger.warning("STT: vad_filter failed (%s), retry without VAD", e)
            segments, info = model.transcribe(wav, **kw)
            text = "".join(s.text for s in segments).strip()

        return {
            "ok": True,
            "text": text,
            "provider": f"local_faster_whisper_{MODEL_SIZE}",
            "language": getattr(info, "language", language),
            "duration": round(float(getattr(info, "duration", 0.0) or 0.0), 2),
        }
    except Exception as e:
        logger.warning("STT transcribe failed: %s", e)
        return {"ok": False, "error": str(e)}
    finally:
        if wav and os.path.exists(wav):
            try:
                os.remove(wav)
            except Exception:
                pass


def warmup():
    """服务启动后台预热，避免首次语音等待模型加载。"""
    try:
        _ensure_model()
    except Exception as e:
        logger.warning("STT warmup failed: %s", e)
