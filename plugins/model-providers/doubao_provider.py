"""Doubao (豆包 / 火山方舟) provider plugin — OpenAI-compatible API via Volcano Ark."""
from providers.base import ProviderProfile
from providers.registry import register

register(ProviderProfile(
    name="doubao",
    display_name="豆包 (火山方舟)",
    base_url="https://ark.cn-beijing.volces.com/api/v3",
    api_key_env="ARK_API_KEY",
    models=[
        "doubao-seed-2.0",
        "doubao-seed-2.0-code",
        "doubao-seed-1.8",
        "doubao-1.5-pro-32k",
    ],
    fallback_models=["doubao-seed-1.8"],
    context_window=256_000,
    supports_vision=True,
    # 火山方舟 Coding 端点走 Anthropic Messages 协议
    anthropic_base_url="https://ark.cn-beijing.volces.com/api/coding",
))
