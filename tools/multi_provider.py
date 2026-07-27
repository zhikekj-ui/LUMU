"""Multi-provider management tools — switch LLM providers and models at runtime."""
import os
from tools.registry import ToolRegistry


def handle_list_providers(**kwargs):
    """List all registered LLM providers and their models."""
    from providers.registry import list_providers, discover_providers
    
    discover_providers()
    providers = list_providers()
    
    result = []
    for p in providers:
        api_key = p.resolve_api_key()
        has_key = bool(api_key and len(api_key) > 8)
        result.append({
            "name": p.name,
            "display_name": p.display_name,
            "base_url": p.base_url,
            "models": p.models,
            "fallback_models": p.fallback_models,
            "context_window": p.context_window,
            "supports_vision": p.supports_vision,
            "supports_streaming": p.supports_streaming,
            "api_key_configured": has_key,
        })
    
    return {"providers": result, "total": len(result)}


def handle_switch_provider(**kwargs):
    """Switch the active LLM provider for the current session.
    
    Args:
        provider: Provider name (e.g., 'stepfun', 'deepseek', 'glm', 'qwen', 'moonshot')
        model: Optional specific model to use
    """
    provider_name = kwargs.get("provider", "")
    model_name = kwargs.get("model", "")
    
    from providers.registry import get as get_provider, discover_providers
    discover_providers()
    
    provider = get_provider(provider_name)
    if not provider:
        available = [p.name for p in __import__("providers.registry", fromlist=["list_providers"]).list_providers()]
        return {"error": f"Provider '{provider_name}' not found. Available: {available}"}
    
    # Check API key (user_config -> env)
    api_key = provider.resolve_api_key()
    if not api_key:
        return {
            "error": f"API key not configured for '{provider_name}'. "
                     f"Set {provider.api_key_env} in .env file.",
        }
    
    # Determine model
    if model_name:
        if model_name not in provider.models:
            return {"error": f"Model '{model_name}' not available for '{provider_name}'. Available: {provider.models}"}
    else:
        model_name = provider.models[0] if provider.models else ""
    
    return {
        "status": "success",
        "provider": provider_name,
        "display_name": provider.display_name,
        "model": model_name,
        "base_url": provider.base_url,
        "context_window": provider.context_window,
        "supports_vision": provider.supports_vision,
        "message": f"已切换到 {provider.display_name}，模型: {model_name}。注意：需要重新创建 Agent 实例才能生效。",
    }


def handle_get_provider_info(**kwargs):
    """Get detailed info about a specific provider."""
    provider_name = kwargs.get("provider", "")
    
    from providers.registry import get as get_provider, discover_providers
    discover_providers()
    
    provider = get_provider(provider_name)
    if not provider:
        return {"error": f"Provider '{provider_name}' not found"}
    
    api_key = provider.resolve_api_key()
    return {
        "name": provider.name,
        "display_name": provider.display_name,
        "base_url": provider.base_url,
        "api_key_env": provider.api_key_env,
        "api_key_configured": bool(api_key and len(api_key) > 8),
        "api_key_preview": api_key[:8] + "..." if api_key else "",
        "models": provider.models,
        "fallback_models": provider.fallback_models,
        "context_window": provider.context_window,
        "supports_vision": provider.supports_vision,
        "supports_streaming": provider.supports_streaming,
        "auth_type": provider.auth_type,
    }


def handle_compare_models(**kwargs):
    """Compare available models across all providers."""
    from providers.registry import list_providers, discover_providers
    discover_providers()
    
    providers = list_providers()
    comparison = []
    
    for p in providers:
        api_key = os.getenv(p.api_key_env, "")
        if not api_key:
            continue  # Skip unconfigured providers
        
        for model in p.models:
            comparison.append({
                "provider": p.display_name,
                "model": model,
                "context_window": p.context_window,
                "vision": p.supports_vision,
                "streaming": p.supports_streaming,
            })
    
    return {
        "models": comparison,
        "total": len(comparison),
        "note": "仅显示已配置API Key的Provider",
    }


def register(registry: ToolRegistry):
    """Register multi-provider management tools."""
    registry.register(
        name="list_providers",
        description="列出所有已注册的LLM Provider及其模型列表，包括配置状态",
        handler=handle_list_providers,
        toolset="provider",
        parameters={},
    )
    
    registry.register(
        name="switch_provider",
        description="切换当前使用的LLM Provider和模型。支持 stepfun/deepseek/glm/qwen/moonshot/openai",
        handler=handle_switch_provider,
        toolset="provider",
        parameters={
            "provider": {"type": "string", "description": "Provider名称", "required": True},
            "model": {"type": "string", "description": "指定模型名称（可选）", "required": False},
        },
    )
    
    registry.register(
        name="get_provider_info",
        description="获取指定Provider的详细信息，包括API配置、模型列表、能力等",
        handler=handle_get_provider_info,
        toolset="provider",
        parameters={
            "provider": {"type": "string", "description": "Provider名称", "required": True},
        },
    )
    
    registry.register(
        name="compare_models",
        description="比较所有已配置Provider的模型能力（上下文窗口、视觉支持等）",
        handler=handle_compare_models,
        toolset="provider",
        parameters={},
    )
