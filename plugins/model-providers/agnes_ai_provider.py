"""Agnes AI 备用供应商 — 指向 https://api.agnes-ai.cn/v1 端点。

独立备用供应商，注册 chat/文本类模型（agnes-2.5-flash / agnes-2.5-pro-alpha）。
另有图像模型 agnes-image-2.1-flash、视频模型 agnes-video-v2.0，可作为媒体生成备用。
模型列表来自 https://api.agnes-ai.cn/v1/models 实测。
"""
from providers.base import ProviderProfile
from providers.registry import register

register(ProviderProfile(
    name="agnes_ai",
    display_name="Agnes AI（备用）",
    base_url="https://api.agnes-ai.cn/v1",
    api_key_env="AGNES_AI_API_KEY",
    models=[
        "agnes-2.5-flash",
        "agnes-2.5-pro-alpha",
    ],
    fallback_models=["agnes-2.5-flash"],
    context_window=128_000,
    supports_vision=False,
))
