"""GLM (智谱AI) provider plugin — OpenAI-compatible API."""
from providers.base import ProviderProfile
from providers.registry import register

register(ProviderProfile(
    name="glm",
    display_name="GLM (智谱AI)",
    base_url="https://open.bigmodel.cn/api/paas/v4",
    api_key_env="GLM_API_KEY",
    models=[
        "glm-4-plus",
        "glm-4",
        "glm-4-flash",
        "glm-4-long",
        "glm-4v-plus",
    ],
    fallback_models=["glm-4-flash"],
    context_window=128_000,
    supports_vision=True,
    anthropic_base_url="https://open.bigmodel.cn/api/anthropic",
))
