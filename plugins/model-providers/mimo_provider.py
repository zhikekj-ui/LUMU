"""Xiaomi MiMo model provider — OpenAI-compatible + Anthropic-compatible API.

Official platform: https://platform.xiaomimimo.com
OpenAI-compatible base_url: https://api.xiaomimimo.com/v1
Anthropic-compatible base_url: https://api.xiaomimimo.com/anthropic
API key env: MIMO_API_KEY (format: sk-xxxxx)
"""
from providers.base import ProviderProfile
from providers.registry import register

register(ProviderProfile(
    name="mimo",
    display_name="小米 MiMo (OpenAI 兼容)",
    base_url="https://api.xiaomimimo.com/v1",
    api_key_env="MIMO_API_KEY",
    models=[
        "mimo-v2.5-pro",
        "mimo-v2-flash",
        "mimo-v2-pro",
        "mimo-v2",
    ],
    fallback_models=["mimo-v2-flash"],
    context_window=128_000,
    supports_vision=False,
    anthropic_base_url="https://api.xiaomimimo.com/anthropic",
))
