"""MiniMax provider plugin — OpenAI-compatible + Anthropic-compatible API."""
from providers.base import ProviderProfile
from providers.registry import register

register(ProviderProfile(
    name="minimax",
    display_name="MiniMax",
    base_url="https://api.minimaxi.com/v1",
    api_key_env="MINIMAX_API_KEY",
    models=[
        "MiniMax-M2.5",
        "MiniMax-M2",
        "MiniMax-Text-01",
    ],
    fallback_models=["MiniMax-M2"],
    context_window=200_000,
    anthropic_base_url="https://api.minimaxi.com/anthropic",
))
