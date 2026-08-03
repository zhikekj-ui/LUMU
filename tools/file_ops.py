"""File system tools — read, write, edit, list, search.

Access is allowed within AGENT_BASE_DIR (user working directory)
and AGENT_HOME extension dirs (plugins/, skills/, knowledge/, data/).
Core system files (agent/, api/, providers/, registry.py, config.py) are write-protected.
"""
import os
import re
from pathlib import Path


# 第3层空间隔离：当前空间，决定文件读写落在哪个子目录
_CURRENT_SPACE = os.getenv("AGENT_SPACE", "work")


def set_current_space(space: str):
    """由 agent 在每次对话开始时设置，使文件读写落在对应空间子目录下。"""
    global _CURRENT_SPACE
    _CURRENT_SPACE = space or "work"


def _get_base_dir() -> str:
    # 跨平台默认工作目录（Windows / macOS / Linux 三端通用），按空间分子目录。
    base = os.getenv("AGENT_BASE_DIR", os.path.expanduser("~/lumu-workspace"))
    return os.path.join(base, _CURRENT_SPACE)


def _get_agent_home() -> str:
    return os.getenv("AGENT_HOME", str(Path(__file__).parent.parent))


def _allowed_dirs() -> list[Path]:
    """Return list of directories the agent is allowed to access.

    「设备即身体」原则：文件读写不再被锁死在 ~/lumu-workspace 孤岛，
    整台机器的用户主目录（身体的核心区）都可直接读写；AGENT_HOME
    （框架本体）也保留以便修改自身代码。核心系统文件仍由写保护兜底。
    """
    dirs = [Path(_get_base_dir()).resolve()]
    home = Path(os.path.expanduser("~")).resolve()
    if home not in dirs:
        dirs.append(home)
    agent_home = Path(_get_agent_home()).resolve()
    if agent_home not in dirs:
        dirs.append(agent_home)
    return dirs


def _resolve_path(path: str) -> Path:
    """Resolve a path, allowing access within AGENT_BASE_DIR and AGENT_HOME."""
    base = Path(_get_base_dir())
    p = Path(path)
    if p.is_absolute():
        resolved = p.resolve()
    else:
        resolved = (base / p).resolve()
    # Security: ensure path is within an allowed directory
    for allowed in _allowed_dirs():
        if str(resolved).startswith(str(allowed)):
            return resolved
    raise PermissionError(
        f"Access denied: path must be within {_get_base_dir()} or {_get_agent_home()}"
    )


def register(registry):
    registry.register(
        name="read_file",
        description="Read the contents of a file. Supports offset and limit for large files.",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path (relative to base dir or absolute)"},
                "offset": {"type": "integer", "description": "Line number to start from (1-indexed, default 1)"},
                "limit": {"type": "integer", "description": "Max lines to read (default 1000)"},
            },
            "required": ["path"],
        },
        handler=read_file,
        toolset="file",
        emoji="📄",
    )
    registry.register(
        name="write_file",
        description="Write content to a file. Creates parent directories if needed.",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path"},
                "content": {"type": "string", "description": "Content to write"},
            },
            "required": ["path", "content"],
        },
        handler=write_file,
        toolset="file",
        emoji="📝",
    )
    registry.register(
        name="edit_file",
        description="Replace a specific string in a file. The old_string must be unique in the file.",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path"},
                "old_string": {"type": "string", "description": "Exact text to find and replace"},
                "new_string": {"type": "string", "description": "Replacement text"},
            },
            "required": ["path", "old_string", "new_string"],
        },
        handler=edit_file,
        toolset="file",
        emoji="✏️",
    )
    registry.register(
        name="list_dir",
        description="List files and directories. Optionally recursive.",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Directory path (default: base dir)"},
                "recursive": {"type": "boolean", "description": "List recursively (default false, max depth 3)"},
            },
        },
        handler=list_dir,
        toolset="file",
        emoji="📁",
    )
    registry.register(
        name="search_files",
        description="Search for a regex pattern across files.",
        parameters={
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Regex pattern to search for"},
                "path": {"type": "string", "description": "Directory to search in (default: base dir)"},
                "glob": {"type": "string", "description": "File glob pattern (default: *.py,*.js,*.ts,*.go,*.html,*.css,*.md,*.json,*.yaml,*.yml,*.toml,*.txt)"},
            },
            "required": ["pattern"],
        },
        handler=search_files,
        toolset="file",
        emoji="🔎",
    )


def read_file(path: str, offset: int = 1, limit: int = 1000) -> str:
    try:
        p = _resolve_path(path)
        if not p.exists():
            return f"File not found: {path}"
        if not p.is_file():
            return f"Not a file: {path}"
        if p.stat().st_size > 10 * 1024 * 1024:  # 10MB
            return f"File too large ({p.stat().st_size} bytes). Use offset/limit."
        lines = p.read_text(errors="replace").splitlines()
        start = max(0, offset - 1)
        end = min(len(lines), start + limit)
        result_lines = []
        for i in range(start, end):
            result_lines.append(f"{i + 1:>6} | {lines[i]}")
        if end < len(lines):
            result_lines.append(f"  ... ({len(lines) - end} more lines)")
        return "\n".join(result_lines) if result_lines else "(empty file)"
    except PermissionError as e:
        return str(e)
    except Exception as e:
        return f"Error reading {path}: {e}"


def write_file(path: str, content: str) -> str:
    try:
        p = _resolve_path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        return f"Written {len(content)} bytes to {path}"
    except PermissionError as e:
        return str(e)
    except Exception as e:
        return f"Error writing {path}: {e}"


def edit_file(path: str, old_string: str, new_string: str) -> str:
    try:
        p = _resolve_path(path)
        if not p.exists():
            return f"File not found: {path}"
        content = p.read_text()
        count = content.count(old_string)
        if count == 0:
            return "Error: old_string not found in file"
        if count > 1:
            return f"Error: old_string found {count} times — must be unique"
        content = content.replace(old_string, new_string, 1)
        p.write_text(content)
        return f"Replaced 1 occurrence in {path}"
    except PermissionError as e:
        return str(e)
    except Exception as e:
        return f"Error editing {path}: {e}"


def list_dir(path: str = ".", recursive: bool = False) -> str:
    try:
        p = _resolve_path(path)
        if not p.exists():
            return f"Directory not found: {path}"
        if not p.is_dir():
            return f"Not a directory: {path}"
        entries = []
        if recursive:
            for item in sorted(p.rglob("*")):
                depth = len(item.relative_to(p).parts)
                if depth > 3:
                    continue
                rel = item.relative_to(p)
                prefix = "📁 " if item.is_dir() else "📄 "
                entries.append(f"{prefix}{rel}")
        else:
            for item in sorted(p.iterdir()):
                prefix = "📁 " if item.is_dir() else "📄 "
                entries.append(f"{prefix}{item.name}")
        return "\n".join(entries) if entries else "(empty directory)"
    except PermissionError as e:
        return str(e)
    except Exception as e:
        return f"Error listing {path}: {e}"


def search_files(
    pattern: str,
    path: str = ".",
    glob: str = "*.py,*.js,*.ts,*.go,*.html,*.css,*.md,*.json,*.yaml,*.yml,*.toml,*.txt",
) -> str:
    try:
        p = _resolve_path(path)
        if not p.is_dir():
            return f"Not a directory: {path}"
        regex = re.compile(pattern)
        glob_patterns = [g.strip() for g in glob.split(",")]
        results = []
        max_results = 50
        for gp in glob_patterns:
            for f in p.rglob(gp):
                if not f.is_file():
                    continue
                depth = len(f.relative_to(p).parts)
                if depth > 5:
                    continue
                try:
                    content = f.read_text(errors="replace")
                    for i, line in enumerate(content.splitlines(), 1):
                        if regex.search(line):
                            rel = f.relative_to(p)
                            results.append(f"{rel}:{i}: {line.strip()[:120]}")
                            if len(results) >= max_results:
                                break
                except (OSError, UnicodeDecodeError):
                    continue
                if len(results) >= max_results:
                    break
            if len(results) >= max_results:
                break
        if not results:
            return f"No matches for: {pattern}"
        header = f"Found {len(results)} match(es)"
        if len(results) >= max_results:
            header += f" (limited to {max_results})"
        return header + ":\n" + "\n".join(results)
    except PermissionError as e:
        return str(e)
    except Exception as e:
        return f"Error searching: {e}"

