"""SiliconFlow (硅基流动) provider plugin — aggregator, OpenAI + Anthropic compatible."""
from providers.base import ProviderProfile
from providers.registry import register

register(ProviderProfile(
    name="siliconflow",
    display_name="硅基流动 (聚合)",
    base_url="https://api.siliconflow.cn/v1",
    api_key_env="SILICONFLOW_API_KEY",
    models=[
        "deepseek-ai/DeepSeek-V3.2",
        "zai-org/GLM-5",
        "Qwen/Qwen3-235B-A22B",
        "moonshotai/Kimi-K2.5",
    ],
    fallback_models=["deepseek-ai/DeepSeek-V3.2"],
    context_window=128_000,
    anthropic_base_url="https://api.siliconflow.cn/v1/anthropic",
))
