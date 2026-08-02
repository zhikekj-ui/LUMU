"""Code sandbox tools — execute code in Docker-isolated environment."""
import os
from tools.registry import ToolRegistry


def _get_sandbox():
    """Lazy-init code sandbox. Network is ON by default (open-box experience);
    opt out via LUMU_SANDBOX_ALLOW_NETWORK=0/false/no/off."""
    from sandbox.executor import CodeSandbox
    env = os.getenv("LUMU_SANDBOX_ALLOW_NETWORK", "1")
    allow = env.strip().lower() not in ("0", "false", "no", "off")
    return CodeSandbox(allow_network=allow)


def handle_run_python(**kwargs):
    """Execute Python code in a sandboxed environment.
    
    Args:
        code: Python code to execute
        timeout: Execution timeout in seconds (default: 30)
        packages: Optional list of pip packages to install
    """
    code = kwargs.get("code", "")
    timeout = kwargs.get("timeout", 30)
    packages = kwargs.get("packages", [])
    
    if isinstance(packages, str):
        import json
        try:
            packages = json.loads(packages)
        except Exception:
            packages = [p.strip() for p in packages.split(",") if p.strip()]
    
    if not code.strip():
        return {"error": "Code is empty"}
    
    try:
        sandbox = _get_sandbox()
        result = sandbox.execute_python(code, timeout=timeout, packages=packages)
        return result
    except Exception as e:
        return {"error": str(e)}


def handle_run_javascript(**kwargs):
    """Execute JavaScript code in a sandboxed environment.
    
    Args:
        code: JavaScript code to execute
        timeout: Execution timeout in seconds (default: 30)
        packages: Optional list of npm packages to install
    """
    code = kwargs.get("code", "")
    timeout = kwargs.get("timeout", 30)
    packages = kwargs.get("packages", [])
    
    if isinstance(packages, str):
        import json
        try:
            packages = json.loads(packages)
        except Exception:
            packages = [p.strip() for p in packages.split(",") if p.strip()]
    
    if not code.strip():
        return {"error": "Code is empty"}
    
    try:
        sandbox = _get_sandbox()
        result = sandbox.execute_javascript(code, timeout=timeout, packages=packages)
        return result
    except Exception as e:
        return {"error": str(e)}


def handle_sandbox_status(**kwargs):
    """Get sandbox environment status and capabilities."""
    try:
        sandbox = _get_sandbox()
        return sandbox.status()
    except Exception as e:
        return {"error": str(e)}


def register(registry: ToolRegistry):
    """Register code sandbox tools."""
    registry.register(
        name="run_python",
        description="在Docker隔离沙箱中执行Python代码。支持安装额外pip包。有超时和资源限制。可定义result变量捕获返回值。",
        handler=handle_run_python,
        toolset="sandbox",
        parameters={
            "code": {"type": "string", "description": "Python代码", "required": True},
            "timeout": {"type": "integer", "description": "超时秒数（默认30）", "required": False},
            "packages": {"type": "string", "description": "pip包列表（JSON数组或逗号分隔）", "required": False},
        },
    )
    
    registry.register(
        name="run_javascript",
        description="在Docker隔离沙箱中执行JavaScript代码（Node.js环境）。支持安装npm包。",
        handler=handle_run_javascript,
        toolset="sandbox",
        parameters={
            "code": {"type": "string", "description": "JavaScript代码", "required": True},
            "timeout": {"type": "integer", "description": "超时秒数（默认30）", "required": False},
            "packages": {"type": "string", "description": "npm包列表", "required": False},
        },
    )
    
    registry.register(
        name="sandbox_status",
        description="获取代码沙箱环境状态（Docker可用性、默认配置等）。",
        handler=handle_sandbox_status,
        toolset="sandbox",
        parameters={},
    )
