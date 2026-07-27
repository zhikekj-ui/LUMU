"""Qwen (通义千问) provider plugin — OpenAI-compatible API via DashScope."""
from providers.base import ProviderProfile
from providers.registry import register

register(ProviderProfile(
    name="qwen",
    display_name="Qwen (通义千问)",
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    api_key_env="QWEN_API_KEY",
    models=[
        "qwen-turbo",
        "qwen-plus",
        "qwen-max",
        "qwen-long",
        "qwen-vl-plus",
    ],
    fallback_models=["qwen-turbo"],
    context_window=128_000,
    supports_vision=True,
))
