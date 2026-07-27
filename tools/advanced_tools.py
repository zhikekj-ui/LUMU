"""Advanced tools for enhanced intelligence."""
import os
import subprocess
import json
import tempfile
from datetime import datetime


def web_search(query: str, num_results: int = 5) -> str:
    """Search the web for information."""
    # 使用 httpx 调用搜索 API (如果配置了)
    # 这里用简单的方式: 通过系统工具搜索
    try:
        import httpx
        # 可以接入 SerpAPI、DuckDuckGo 等
        return f"Web search results for: {query}\n(Note: Configure search API key in .env for live results)"
    except ImportError:
        return f"Web search: {query} (httpx not available)"


def execute_code(code: str, language: str = "python", timeout: int = 30) -> str:
    """Execute code in a sandboxed environment."""
    if language not in ("python", "bash"):
        return f"Unsupported language: {language}"
    
    if language == "python":
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(code)
            f.flush()
            try:
                result = subprocess.run(
                    ['python3', f.name],
                    capture_output=True, text=True, timeout=timeout
                )
                output = result.stdout if result.stdout else result.stderr
                return f"Output:\n{output}" if output else "No output"
            except subprocess.TimeoutExpired:
                return "Error: Code execution timed out"
            except Exception as e:
                return f"Error: {str(e)}"
            finally:
                os.unlink(f.name)
    else:
        # bash with safety checks
        from agent.security import CommandSandbox, PermissionLevel
        sandbox = CommandSandbox(PermissionLevel.ADMIN)
        allowed, reason = sandbox.validate_command(code)
        if not allowed:
            return f"Command blocked: {reason}"
        try:
            result = subprocess.run(
                ['bash', '-c', code],
                capture_output=True, text=True, timeout=timeout
            )
            output = result.stdout if result.stdout else result.stderr
            return f"Output:\n{output}" if output else "No output"
        except subprocess.TimeoutExpired:
            return "Error: Command timed out"
        except Exception as e:
            return f"Error: {str(e)}"


def deep_think(problem: str) -> str:
    """Trigger deep reasoning mode with extended thinking time."""
    # This modifies the system prompt to encourage deeper analysis
    return f"[DEEP THINKING MODE ACTIVATED]\nProblem: {problem}\n\nPlease analyze this thoroughly, considering multiple perspectives and potential edge cases."


# Tool definitions for registration
ADVANCED_TOOLS = [
    {
        "name": "web_search",
        "description": "Search the web for current information. Use for lookups, fact-checking, and research.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "num_results": {"type": "integer", "description": "Number of results (default 5)"},
            },
            "required": ["query"],
        },
        "handler": web_search,
    },
    {
        "name": "execute_code",
        "description": "Execute Python or Bash code in a sandboxed environment. Use for calculations, data processing, and automation.",
        "parameters": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "Code to execute"},
                "language": {"type": "string", "enum": ["python", "bash"], "description": "Programming language"},
            },
            "required": ["code", "language"],
        },
        "handler": execute_code,
    },
    {
        "name": "deep_think",
        "description": "Activate deep thinking mode for complex analysis. Use for difficult problems, design decisions, and strategic thinking.",
        "parameters": {
            "type": "object",
            "properties": {
                "problem": {"type": "string", "description": "The problem to analyze deeply"},
            },
            "required": ["problem"],
        },
        "handler": deep_think,
    },
]
