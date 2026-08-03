"""Tool registry — AST-based auto-discovery + generation counter (from Hermes Agent)."""
import ast
import importlib.util
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


# ── Core write protection ──
# These paths are the agent's "brain" — read-only at runtime.
# The agent extends itself via plugins/, skills/, knowledge/ instead.
_BASE = Path(__file__).parent.parent.resolve()

PROTECTED_DIRS = [
    _BASE / "agent",
    _BASE / "api",
    _BASE / "providers",
]

PROTECTED_FILES = [
    _BASE / "tools" / "registry.py",
    _BASE / "config.py",
    _BASE / "run.py",
    _BASE / ".env",
]

# Tools that write/modify files — their arguments get path-checked
_WRITE_TOOLS = {"write_file", "edit_file", "terminal"}


from core.logging_config import get_logger
_logger = get_logger("tools.registry")

def _is_protected_path(file_path: str) -> bool:
    """Check if a path is inside the protected core zone."""
    try:
        p = Path(file_path).resolve()
        # Check protected directories
        for d in PROTECTED_DIRS:
            if str(p).startswith(str(d) + "/"):
                return True
        # Check protected files
        for f in PROTECTED_FILES:
            if p == f:
                return True
    except Exception:
        pass
    return False


def _check_write_protection(tool_name: str, arguments: dict) -> str | None:
    """Return error message if tool call violates core protection, else None."""
    if tool_name not in _WRITE_TOOLS:
        return None

    if tool_name in ("write_file", "edit_file"):
        target = arguments.get("path", "")
        if _is_protected_path(target):
            return (
                f"⛔ 核心文件保护：{target} 属于系统核心，不可修改。\n"
                f"如需扩展能力，请在 plugins/、skills/、knowledge/ 目录下创建新文件。"
            )

    if tool_name == "terminal":
        cmd = arguments.get("command", "")
        # Check if command references protected paths
        import re
        # Match paths that look like they're modifying core files
        _home_for_regex = os.getenv("AGENT_HOME", str(Path(__file__).resolve().parent.parent))
        dangerous_patterns = [
            rf"{re.escape(_home_for_regex)}/(agent|api|providers)/",
            r"/opt/agent-framework/(agent|api|providers)/",  # 服务器默认路径兜底
            r"config\.py",
            r"registry\.py",
            r"\.env",
            r"run\.py",
        ]
        for pattern in dangerous_patterns:
            if re.search(pattern, cmd):
                return (
                    f"⛔ 核心保护：该命令可能修改系统核心文件。\n"
                    f"扩展能力请使用 plugins/、skills/、knowledge/ 目录。"
                )

    return None


@dataclass(slots=True)
class ToolEntry:
    name: str
    description: str
    parameters: dict
    handler: Callable
    toolset: str = "default"
    is_async: bool = False
    max_result_chars: int = 100_000
    emoji: str = "🔧"


class ToolRegistry:
    """Tool registry with generation counter for cache invalidation.

    The generation counter increments on every register/discover call,
    so the agent can detect when tool schemas have changed and avoid
    sending stale function definitions to the LLM.
    """

    def __init__(self):
        self._tools: dict[str, ToolEntry] = {}
        self._generation: int = 0
        self._toolsets: dict[str, list[str]] = {}  # toolset_name → [tool_names]

    @property
    def generation(self) -> int:
        return self._generation

    def register(
        self,
        name: str,
        description: str,
        parameters: dict,
        handler: Callable,
        toolset: str = "default",
        is_async: bool = False,
        emoji: str = "🔧",
    ):
        self._tools[name] = ToolEntry(
            name=name,
            description=description,
            parameters=parameters,
            handler=handler,
            toolset=toolset,
            is_async=is_async,
            emoji=emoji,
        )
        # Track toolset membership
        self._toolsets.setdefault(toolset, [])
        if name not in self._toolsets[toolset]:
            self._toolsets[toolset].append(name)
        self._generation += 1

    def get(self, name: str) -> ToolEntry | None:
        return self._tools.get(name)

    def list_tools(self, toolsets: set[str] | None = None) -> list[ToolEntry]:
        """List tools, optionally filtered by toolset names."""
        if toolsets is None:
            return list(self._tools.values())
        return [t for t in self._tools.values() if t.toolset in toolsets]

    def list_toolsets(self) -> dict[str, list[str]]:
        """Return all toolset names and their member tools."""
        return dict(self._toolsets)

    @staticmethod
    def _to_json_schema(params: dict) -> dict:
        """Convert custom parameter format to JSON Schema if needed."""
        # Already proper JSON Schema
        if params.get("type") == "object" or "properties" in params:
            return params
        # Empty parameters
        if not params:
            return {"type": "object", "properties": {}}
        # Convert custom format: {"name": {"type": ..., "description": ..., "required": bool}}
        properties = {}
        required = []
        for key, spec in params.items():
            prop = {}
            if isinstance(spec, dict):
                if "type" in spec:
                    prop["type"] = spec["type"]
                if "description" in spec:
                    prop["description"] = spec["description"]
                if "enum" in spec:
                    prop["enum"] = spec["enum"]
                if spec.get("required"):
                    required.append(key)
            else:
                prop["type"] = "string"
            properties[key] = prop
        schema = {"type": "object", "properties": properties}
        if required:
            schema["required"] = required
        return schema

    def to_openai_schemas(self, toolsets: set[str] | None = None) -> list[dict]:
        """Generate OpenAI function-calling schemas, optionally filtered by toolset."""
        tools = self.list_tools(toolsets)
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": self._to_json_schema(t.parameters),
                },
            }
            for t in tools
        ]

    async def execute(self, name: str, arguments: dict) -> str:
        tool = self._tools.get(name)
        if not tool:
            return f"Error: tool '{name}' not found"

        # ── Core write protection ──
        violation = _check_write_protection(name, arguments)
        if violation:
            return violation

        try:
            if tool.is_async:
                result = await tool.handler(**arguments)
            else:
                result = tool.handler(**arguments)
            result_str = str(result)
            if len(result_str) > tool.max_result_chars:
                result_str = result_str[: tool.max_result_chars] + "\n...[truncated]"
            return result_str
        except Exception as e:
            return f"Error executing {name}: {e}"

    def discover(self, tools_dir: Path | None = None):
        """AST-based tool discovery — no imports needed (from Hermes Agent)."""
        if tools_dir is None:
            tools_dir = Path(__file__).parent
        for f in tools_dir.glob("*.py"):
            if f.name.startswith("_") or f.name == "registry.py":
                continue
            try:
                self._discover_in_file(f)
            except Exception as e:
                _logger.info(f"[warn] AST scan {f.name}: {e}")
        # Bump generation once per discover() call (not per tool)
        self._generation += 1

    def _discover_in_file(self, filepath: Path):
        source = filepath.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=filepath)
        has_register = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Attribute) and func.attr == "register":
                    has_register = True
                    break
                if isinstance(func, ast.Name) and func.id == "register":
                    has_register = True
                    break
        if not has_register:
            return
        spec = importlib.util.spec_from_file_location(filepath.stem, filepath)
        mod = importlib.util.module_from_spec(spec)
        mod.registry = self
        spec.loader.exec_module(mod)
        # Call the module's register() function to actually register tools
        if hasattr(mod, "register") and callable(mod.register):
            mod.register(self)
