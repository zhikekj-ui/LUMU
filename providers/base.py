"""Provider abstraction layer - ProviderProfile dataclass."""
from dataclasses import dataclass, field
import os


@dataclass
class ProviderProfile:
    """Declarative description of an LLM provider.
    Pure data — no client construction logic.
    """
    name: str
    display_name: str
    base_url: str
    api_key_env: str
    models: list[str] = field(default_factory=list)
    fallback_models: list[str] = field(default_factory=list)
    context_window: int = 128_000
    supports_vision: bool = False
    supports_streaming: bool = True
    auth_type: str = "bearer"  # bearer | api-key
    anthropic_base_url: str = ""  # 该厂商的 Anthropic 兼容端点（留空 = 仅支持 OpenAI 协议）

    def resolve_api_key(self) -> str:
        """Resolve API key: user_config.json -> env var."""
        try:
            from core.user_config import get_provider_key
            key = get_provider_key(self.name)
            if key:
                return key
        except Exception:
            pass
        return os.getenv(self.api_key_env, "")

    def resolve_base_url(self) -> str:
        """Resolve base_url with override priority:

        env var ``{NAME}_BASE_URL`` -> user_config ``provider_overrides``
        -> provider default.

        Lets end users point at any OpenAI-compatible endpoint (local
        ollama, self-hosted gateway, etc.) **without editing provider code**.
        """
        env_key = f"{self.name.upper()}_BASE_URL"
        env_val = os.getenv(env_key, "")
        if env_val:
            return env_val
        try:
            from core.user_config import get_provider_override
            override = get_provider_override(self.name)
            if override and override.get("base_url"):
                return override["base_url"]
        except Exception:
            pass
        return self.base_url
