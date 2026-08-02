"""StepFun plan 备用供应商 — 指向 step_plan 专用端点。

独立于标准 stepfun provider，作为备用供应商使用，避免覆盖原有 v1 配置。
模型列表来自 https://api.stepfun.com/step_plan/v1/models 实测（仅注册 chat/文本类模型）。
"""
from providers.base import ProviderProfile
from providers.registry import register

register(ProviderProfile(
    name="stepfun_plan",
    display_name="StepFun Plan (备用)",
    base_url="https://api.stepfun.com/step_plan/v1",
    api_key_env="STEPFUN_PLAN_API_KEY",
    models=[
        "step-3.7-flash",
        "step-router-v1",
        "step-3.5-flash",
        "step-3.5-flash-2603",
    ],
    fallback_models=["step-3.7-flash", "step-router-v1"],
    context_window=128_000,
    supports_vision=True,
))
