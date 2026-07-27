"""工具暴露策略 — 核心工具常驻 + 其余按需激活（降低每条消息的 prompt token）。

背景：126 个工具的 schema 全量暴露 ≈ 14.9k tokens/消息。
策略（TOOL_EXPOSURE 环境变量）：
  - core（默认）：只暴露 CORE_TOOLSETS + 已激活的扩展工具集
  - all：全量暴露（回滚开关，行为与旧版完全一致）
扩展工具集通过 tool_find 工具按需激活，TTL 过期后自动收回。
"""
import os
import time

# 常驻核心：终端/文件/搜索/时间/代码沙箱/审批/技能/记忆 ≈ 3.6k tokens
CORE_TOOLSETS = {
    "terminal", "file", "search", "system", "sandbox",
    "hitl", "skills", "memory",
}

TTL_SECONDS = int(os.getenv("TOOL_ACTIVATION_TTL", "900"))  # 激活后保留 15 分钟

_active: dict[str, float] = {}  # toolset -> 过期时间戳


def exposure_policy() -> str:
    return os.getenv("TOOL_EXPOSURE", "core").lower()


def activate_toolsets(names: list[str]) -> list[str]:
    """激活扩展工具集，返回实际激活的列表。"""
    now = time.time()
    out = []
    for n in names:
        if n and n not in CORE_TOOLSETS:
            _active[n] = now + TTL_SECONDS
            out.append(n)
    return out


def get_exposed_toolsets() -> frozenset:
    """当前应暴露的工具集（核心 + 未过期的激活项）。"""
    now = time.time()
    for k in [k for k, exp in _active.items() if exp < now]:
        _active.pop(k, None)
    return frozenset(CORE_TOOLSETS | set(_active))
