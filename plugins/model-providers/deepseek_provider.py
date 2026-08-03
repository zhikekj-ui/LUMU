"""DeepSeek provider plugin — popular in China, OpenAI-compatible API."""
from providers.base import ProviderProfile
from providers.registry import register

register(ProviderProfile(
    name="deepseek",
    display_name="DeepSeek",
    base_url="https://api.deepseek.com/v1",
    api_key_env="DEEPSEEK_API_KEY",
    models=["deepseek-v4-flash", "deepseek-v4-pro"],
    fallback_models=["deepseek-v4-flash"],
    context_window=128_000,
    anthropic_base_url="https://api.deepseek.com/anthropic",
    supports_vision=False,
))
