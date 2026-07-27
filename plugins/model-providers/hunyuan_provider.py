"""Tencent Hunyuan (腾讯混元) provider plugin — OpenAI-compatible + Anthropic-compatible API."""
from providers.base import ProviderProfile
from providers.registry import register

register(ProviderProfile(
    name="hunyuan",
    display_name="腾讯混元",
    base_url="https://api.hunyuan.cloud.tencent.com/v1",
    api_key_env="HUNYUAN_API_KEY",
    models=[
        "hunyuan-2.0-thinking-20251109",
        "hunyuan-2.0-instruct-20251111",
        "hunyuan-turbos-latest",
    ],
    fallback_models=["hunyuan-turbos-latest"],
    context_window=128_000,
    anthropic_base_url="https://api.hunyuan.cloud.tencent.com/anthropic",
))
