"""OpenAI provider plugin — auto-discovered by providers/registry.py."""
import os
from providers.base import ProviderProfile
from providers.registry import register

register(ProviderProfile(
    name="openai",
    display_name="OpenAI 兼容（可自定义 Base URL）",
    base_url="https://api.openai.com/v1",
    api_key_env="OPENAI_API_KEY",
    models=["gpt-4o-mini", "gpt-4o", "gpt-4.1-mini", "gpt-4.1"],
    fallback_models=["gpt-4o-mini"],
    context_window=128_000,
    supports_vision=True,
))
