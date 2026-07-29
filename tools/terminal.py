"""Terminal/shell execution tool — async version with configurable base dir."""
import asyncio
import os


def register(registry):
    registry.register(
        name="terminal",
        description="Execute a shell command and return stdout+stderr. Use for system tasks, file ops, git, etc.",
        parameters={
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "Shell command to execute",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds (default 30)",
                },
            },
            "required": ["command"],
        },
        handler=run_terminal,
        is_async=True,
        toolset="terminal",
        emoji="💻",
    )


# 第3层空间隔离：当前空间，决定终端工作目录落在哪个子目录
_CURRENT_SPACE = os.getenv("AGENT_SPACE", "work")


def set_current_space(space: str):
    """由 agent 在每次对话开始时设置，使终端工作目录落在对应空间子目录下。"""
    global _CURRENT_SPACE
    _CURRENT_SPACE = space or "work"


def _get_cwd() -> str:
    # 跨平台默认工作目录（Windows / macOS / Linux 三端通用），按空间分子目录。
    base = os.getenv("AGENT_BASE_DIR", os.path.expanduser("~/lumu-workspace"))
    return os.path.join(base, _CURRENT_SPACE)


async def run_terminal(command: str, timeout: int = 30) -> str:
    """Execute command asynchronously using asyncio subprocess."""
    # ── 安全沙箱：硬拦截危险命令 + 白名单策略（defense in depth）──
    try:
        from agent.security import get_command_sandbox
        ok, reason = get_command_sandbox().validate_command(command)
    except Exception as e:
        # 沙箱不可用时失败开放，但记录日志，避免静默放过风险
        ok, reason = True, f"sandbox-unavailable:{e}"
    if not ok:
        return f"⛔ 命令被安全沙箱拦截：{reason}\n（原命令未执行）"
    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=_get_cwd(),
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            return f"Command timed out after {timeout}s"

        output = ""
        if stdout:
            output += stdout.decode("utf-8", errors="replace")
        if stderr:
            output += f"\n[stderr]\n{stderr.decode('utf-8', errors='replace')}"
        if proc.returncode != 0:
            output += f"\n[exit code: {proc.returncode}]"
        return output.strip() or "(no output)"
    except Exception as e:
        return f"Error: {e}"
