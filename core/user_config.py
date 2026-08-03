"""User configuration manager — stores API keys and preferences in JSON."""
import json
import os
from pathlib import Path

CONFIG_PATH = Path(__file__).parent.parent / "data" / "user_config.json"

_DEFAULT_CONFIG = {
    "providers": {},   # {"glm": {"api_key": "xxx"}, "qwen": {"api_key": "yyy"}}
    "tts": {
        "default_provider": "edge",  # edge (free) or mimo (needs key)
        "mimo_api_key": "",
    },
    "stt": {
        "default_provider": "whisper",  # whisper (StepFun API) or google
    },
    # 轻量对话模式：默认开启。开启后普通聊天只做 1 次模型调用（记忆召回 + RAG +
    # 主回答），跳过深度推理 / 多轮自校正 / 多重规划等额外串行调用，显著降低首字
    # 延迟（尤其在使用国内较慢的 OpenAI 兼容服务时）。复杂任务可在设置里关闭。
    "chat": {
        "lite_mode": True,
    },
}


def load_config() -> dict:
    """Load user config from disk, creating default if missing."""
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                data = json.load(f)
            # Merge with defaults for any missing keys
            for k, v in _DEFAULT_CONFIG.items():
                if k not in data:
                    data[k] = v
                elif isinstance(v, dict):
                    for sk, sv in v.items():
                        if sk not in data[k]:
                            data[k][sk] = sv
            return data
        except Exception:
            pass
    return json.loads(json.dumps(_DEFAULT_CONFIG))


def save_config(cfg: dict):
    """Persist user config to disk."""
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


def get_provider_key(provider_name: str) -> str:
    """Get API key for a provider. Checks user_config.json first, then env."""
    cfg = load_config()
    provider_cfg = cfg.get("providers", {}).get(provider_name, {})
    key = provider_cfg.get("api_key", "")
    if key:
        return key
    # Fallback to env
    env_map = {
        "stepfun": "STEPFUN_API_KEY",
        "deepseek": "DEEPSEEK_API_KEY",
        "openai": "OPENAI_API_KEY",
        "glm": "GLM_API_KEY",
        "qwen": "QWEN_API_KEY",
        "moonshot": "MOONSHOT_API_KEY",
    }
    env_key = env_map.get(provider_name, f"{provider_name.upper()}_API_KEY")
    return os.getenv(env_key, "")


# In-memory live overrides set via API (no restart needed). Mirrors the
# persisted ``provider_overrides`` section in user_config.json.
_OVERRIDE_CACHE: dict = {}


def get_provider_override(provider_name: str) -> dict:
    """Get per-provider endpoint overrides (e.g. custom base_url).

    Checked in-memory live cache first (set via API), then falls back to
    ``user_config.json["provider_overrides"][provider_name]``.
    Example config::

        {
          "provider_overrides": {
            "deepseek": {"base_url": "http://localhost:11434/v1"}
          }
        }

    Returns an empty dict when no override is configured.
    """
    if provider_name in _OVERRIDE_CACHE and _OVERRIDE_CACHE[provider_name]:
        return _OVERRIDE_CACHE[provider_name]
    cfg = load_config()
    return cfg.get("provider_overrides", {}).get(provider_name, {}) or {}


def set_provider_override(provider_name: str, override: dict) -> bool:
    """Persist a per-provider endpoint override (e.g. custom base_url) and
    apply it live (no restart required).

    ``override`` may contain ``base_url``. Empty/blank values clear the
    override. Returns True on success.
    """
    clean = {}
    base_url = (override or {}).get("base_url", "").strip()
    if base_url:
        clean["base_url"] = base_url.rstrip("/")
    cfg = load_config()
    if "provider_overrides" not in cfg or not isinstance(cfg.get("provider_overrides"), dict):
        cfg["provider_overrides"] = {}
    if clean:
        cfg["provider_overrides"][provider_name] = clean
        _OVERRIDE_CACHE[provider_name] = clean
    else:
        cfg.get("provider_overrides", {}).pop(provider_name, None)
        _OVERRIDE_CACHE.pop(provider_name, None)
    save_config(cfg)
    return True


def set_provider_key(provider_name: str, api_key: str) -> bool:
    """Set API key for a provider in user config."""
    cfg = load_config()
    if "providers" not in cfg:
        cfg["providers"] = {}
    if provider_name not in cfg["providers"]:
        cfg["providers"][provider_name] = {}
    cfg["providers"][provider_name]["api_key"] = api_key
    save_config(cfg)
    return True


def get_enabled_models(provider_name: str) -> list:
    """Get the user-checked (enabled) models for a provider."""
    cfg = load_config()
    models = cfg.get("providers", {}).get(provider_name, {}).get("enabled_models", [])
    return models if isinstance(models, list) else []


def set_enabled_models(provider_name: str, models: list) -> bool:
    """Persist the user-checked (enabled) models for a provider."""
    cfg = load_config()
    if "providers" not in cfg:
        cfg["providers"] = {}
    if provider_name not in cfg["providers"]:
        cfg["providers"][provider_name] = {}
    cfg["providers"][provider_name]["enabled_models"] = [m for m in (models or []) if isinstance(m, str) and m.strip()]
    save_config(cfg)
    return True


def get_tts_config() -> dict:
    """Get TTS configuration."""
    cfg = load_config()
    return cfg.get("tts", _DEFAULT_CONFIG["tts"])


def set_tts_config(provider: str = None, mimo_api_key: str = None):
    """Update TTS configuration."""
    cfg = load_config()
    if "tts" not in cfg:
        cfg["tts"] = _DEFAULT_CONFIG["tts"].copy()
    if provider is not None:
        cfg["tts"]["default_provider"] = provider
    if mimo_api_key is not None:
        cfg["tts"]["mimo_api_key"] = mimo_api_key
    save_config(cfg)


def get_stt_config() -> dict:
    """Get STT configuration."""
    cfg = load_config()
    return cfg.get("stt", _DEFAULT_CONFIG["stt"])


def get_model_preference() -> dict:
    """Get saved model preference (provider + model)."""
    cfg = load_config()
    return cfg.get("model_preference", {})


def set_model_preference(provider: str, model: str):
    """Save model preference to user config."""
    cfg = load_config()
    cfg["model_preference"] = {"provider": provider, "model": model}
    save_config(cfg)


def get_system_prompt() -> str:
    """Get custom system prompt from user config."""
    cfg = load_config()
    return cfg.get("system_prompt", "")


def set_system_prompt(prompt: str):
    """Save custom system prompt to user config."""
    cfg = load_config()
    cfg["system_prompt"] = prompt
    save_config(cfg)


def get_embedding_config() -> dict:
    """Get embedding API configuration."""
    cfg = load_config()
    return {
        "api_key": cfg.get("embedding_api_key", ""),
        "base_url": cfg.get("embedding_base_url", ""),
        "model": cfg.get("embedding_model", ""),
    }


def set_embedding_config(api_key: str = "", base_url: str = "", model: str = ""):
    """Set embedding API configuration."""
    cfg = load_config()
    if api_key:
        cfg["embedding_api_key"] = api_key
    if base_url:
        cfg["embedding_base_url"] = base_url
    if model:
        cfg["embedding_model"] = model
    save_config(cfg)


def get_chat_config() -> dict:
    """Get chat behavior config (currently lite_mode)."""
    cfg = load_config()
    chat = cfg.get("chat", {})
    if not isinstance(chat, dict):
        chat = {}
    return {
        "lite_mode": chat.get("lite_mode", _DEFAULT_CONFIG["chat"]["lite_mode"]),
    }


def set_chat_config(chat_cfg: dict) -> bool:
    """Persist chat behavior config (e.g. {"lite_mode": bool})."""
    if not isinstance(chat_cfg, dict):
        return False
    cfg = load_config()
    cur = cfg.get("chat", {})
    if not isinstance(cur, dict):
        cur = {}
    for k in ("lite_mode",):
        if k in chat_cfg:
            cur[k] = bool(chat_cfg[k])
    cfg["chat"] = cur
    save_config(cfg)
    return True
