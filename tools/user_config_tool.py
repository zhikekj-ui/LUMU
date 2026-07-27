"""User configuration tools — let the agent help users configure API keys and settings."""
from tools.registry import ToolRegistry


def handle_configure_provider(**kwargs):
    """Set API key for an LLM provider.
    
    Args:
        provider: Provider name (stepfun/deepseek/openai/glm/qwen/moonshot)
        api_key: The API key to set
    """
    provider = kwargs.get("provider", "")
    api_key = kwargs.get("api_key", "")
    
    if not provider:
        return {"error": "请指定 provider 名称，如 glm/qwen/moonshot"}
    if not api_key or len(api_key) < 4:
        return {"error": "API Key 太短，请检查"}
    
    from core.user_config import set_provider_key, get_provider_key
    set_provider_key(provider, api_key.strip())
    
    # Verify it was saved
    saved_key = get_provider_key(provider)
    if saved_key:
        preview = saved_key[:4] + "****" + saved_key[-4:] if len(saved_key) > 8 else "已配置"
        return {
            "success": True,
            "provider": provider,
            "api_key_preview": preview,
            "message": f"{provider} 的 API Key 已保存。切换到此 provider 后即可使用。",
        }
    return {"error": "保存失败，请重试"}


def handle_configure_tts(**kwargs):
    """Configure TTS (text-to-speech) settings.
    
    Args:
        provider: TTS provider (edge=免费无需key, mimo=高质量需要key)
        mimo_api_key: MiMo TTS API key (only needed for mimo provider)
    """
    provider = kwargs.get("provider", "")
    mimo_api_key = kwargs.get("mimo_api_key", "")
    
    from core.user_config import set_tts_config
    set_tts_config(provider=provider if provider else None, 
                   mimo_api_key=mimo_api_key if mimo_api_key else None)
    
    result = {"success": True, "message": "TTS 配置已更新"}
    if provider:
        result["provider"] = provider
        if provider == "edge":
            result["note"] = "Edge TTS 免费可用，无需 API Key"
        elif provider == "mimo":
            result["note"] = "MiMo TTS 需要 API Key" + ("（已配置）" if mimo_api_key else "（未配置）")
    return result


def handle_get_config_status(**kwargs):
    """Get current configuration status for all providers and services."""
    from core.user_config import load_config, get_provider_key, get_tts_config, get_stt_config
    from providers.registry import list_providers
    
    providers = list_providers()
    provider_status = []
    for p in providers:
        key = get_provider_key(p.name)
        provider_status.append({
            "name": p.name,
            "display_name": p.display_name,
            "configured": bool(key and len(key) > 4),
            "models": p.models[:3],  # Show first 3 models
        })
    
    tts = get_tts_config()
    stt = get_stt_config()
    
    # Get current active model from agent instance
    current_provider = ""
    current_model = ""
    try:
        from api.main import agent as _agent
        current_provider = getattr(_agent, "provider_name", "")
        current_model = getattr(_agent, "model", "")
    except Exception:
        try:
            from core.user_config import get_model_preference
            pref = get_model_preference()
            current_provider = pref.get("provider", "")
            current_model = pref.get("model", "")
        except Exception:
            pass

    return {
        "current_model": current_model,
        "current_provider": current_provider,
        "current_model_display": f"当前正在使用的模型: {current_provider} / {current_model}",
        "providers": provider_status,
        "tts": {
            "default_provider": tts.get("default_provider", "edge"),
            "mimo_configured": bool(tts.get("mimo_api_key")),
        },
        "stt": {
            "default_provider": stt.get("default_provider", "whisper"),
        },
        "sandbox": {
            "docker_available": _check_docker(),
        },
    }


def _check_docker() -> bool:
    """Check if Docker is available."""
    try:
        import subprocess
        result = subprocess.run(["docker", "info"], capture_output=True, timeout=5)
        return result.returncode == 0
    except Exception:
        return False


def register(registry: ToolRegistry):
    """Register user configuration tools."""
    registry.register(
        name="configure_provider",
        description="为 LLM Provider 设置 API Key。支持: stepfun/deepseek/openai/glm/qwen/moonshot",
        handler=handle_configure_provider,
        toolset="provider",
        parameters={
            "provider": {"type": "string", "description": "Provider 名称", "required": True},
            "api_key": {"type": "string", "description": "API Key", "required": True},
        },
    )
    
    registry.register(
        name="configure_tts",
        description="配置 TTS 语音合成服务。edge=免费无需key, mimo=高质量需要API Key",
        handler=handle_configure_tts,
        toolset="tts_stt",
        parameters={
            "provider": {"type": "string", "description": "TTS provider (edge 或 mimo)", "required": False},
            "mimo_api_key": {"type": "string", "description": "MiMo TTS API Key", "required": False},
        },
    )
    
    registry.register(
        name="get_config_status",
        description="查看当前所有 Provider、TTS、STT、沙箱的配置状态",
        handler=handle_get_config_status,
        toolset="provider",
        parameters={},
    )
