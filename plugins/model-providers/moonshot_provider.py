"""Moonshot (月之暗面) provider plugin — OpenAI-compatible API."""
from providers.base import ProviderProfile
from providers.registry import register

register(ProviderProfile(
    name="moonshot",
    display_name="Moonshot (月之暗面)",
    base_url="https://api.moonshot.cn/v1",
    api_key_env="MOONSHOT_API_KEY",
    models=[
        "moonshot-v1-8k",
        "moonshot-v1-32k",
        "moonshot-v1-128k",
    ],
    fallback_models=["moonshot-v1-32k"],
    context_window=128_000,
    supports_vision=False,
    anthropic_base_url="https://api.moonshot.cn/anthropic",
))
