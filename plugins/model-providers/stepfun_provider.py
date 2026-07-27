"""StepFun model provider — registers step-3.7-flash and vision models."""
from providers.base import ProviderProfile
from providers.registry import register

register(ProviderProfile(
    name="stepfun",
    display_name="StepFun (阶跃星辰)",
    base_url="https://api.stepfun.com/v1",
    api_key_env="STEPFUN_API_KEY",
    models=[
        "step-3.7-flash",
        "step-router-v1",
        "step-3.5-flash",
        "step-3.5-flash-2603",
        "step-1.5v-mini",
        "step-1v-8k",
    ],
    fallback_models=["step-3.7-flash", "step-router-v1"],
    context_window=128_000,
    supports_vision=True,
))
