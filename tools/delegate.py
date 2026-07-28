"""Delegate tool — spawn sub-agents for complex task decomposition.

The main agent can call delegate_task to hand off a sub-task to a
specialized sub-agent. The sub-agent runs in an ISOLATED context (its own
Agent instance, own messages, no memory/session persistence) and returns
only the final result text — the main agent's context is never polluted by
the sub-agent's intermediate tool calls.

Key design decisions:
- Sub-agents share the same provider (no extra API keys needed)
- Sub-agents don't get delegate_task (prevents infinite recursion)
- Sub-agents run with a bounded iteration cap (max_iterations) so a stuck
  sub-task can't burn the whole budget
- Sub-agents use a LITE system prompt (no memory/skill injection) and a
  reduced tool set by default, keeping them cheap and focused
"""
import asyncio


def register(registry):
    registry.register(
        name="delegate_task",
        description=(
            "把一个复杂/多步子任务委派给一个隔离的子代理去独立完成，子代理在独立上下文运行，"
            "只把最终结果返回给你（不走主上下文，避免主会话被中间步骤撑爆）。"
            "适合：长任务、可独立验证的子问题、需要大量工具调用的子环节。"
            "子代理专注完成你指派的任务，不反问、不额外发挥。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "清晰描述子代理要做什么",
                },
                "context": {
                    "type": "string",
                    "description": "相关背景信息（可选），帮助子代理理解任务",
                },
                "toolsets": {
                    "type": "string",
                    "description": "逗号分隔的工具集名（如 'file,terminal'）。不填则子代理默认只拿核心工具集（terminal/file/search/system/sandbox/hitl/skills/memory），更轻量",
                },
            },
            "required": ["task"],
        },
        handler=delegate_task,
        is_async=True,
        toolset="orchestration",
        emoji="🤖",
    )


def _get_agent():
    from agent.core import _agent_instance
    return _agent_instance


_SUB_MAX_ITER = 8  # 子代理迭代上限（防止失控，主代理为 50）


async def delegate_task(task: str, context: str = "", toolsets: str = "") -> str:
    """Spawn an isolated sub-agent to handle a sub-task."""
    try:
        main_agent = _get_agent()
        if main_agent is None:
            return "[子任务失败] 主代理未就绪，无法委派"

        from tools.registry import ToolRegistry
        from tools.exposure import CORE_TOOLSETS

        sub_registry = ToolRegistry()

        # 默认只给核心工具集（轻量）；用户显式指定则尊重
        if toolsets:
            allowed = set(t.strip() for t in toolsets.split(",") if t.strip())
        else:
            allowed = CORE_TOOLSETS

        for tool in main_agent.tools.list_tools(allowed):
            if tool.name == "delegate_task":
                continue  # 子代理绝不能有委派工具，防递归
            sub_registry.register(
                name=tool.name,
                description=tool.description,
                parameters=tool.parameters,
                handler=tool.handler,
                toolset=tool.toolset,
                is_async=tool.is_async,
                emoji=tool.emoji,
            )

        tool_names = [t.name for t in sub_registry.list_tools()]

        # 精简子代理 prompt：不注入记忆/技能/护栏，避免膨胀与对 None 子系统的依赖
        sub_sys = (
            "你是一个专注执行单一子任务的 AI 子代理。规则：\n"
            "1. 只完成被指派的任务，不要反问、不要做任务之外的事\n"
            "2. 完成后用中文给出简洁结论（要点即可，不要冗长）\n"
            "3. 你没有委派工具，不要尝试委派任务\n"
        )
        if context:
            sub_sys += f"\n任务背景：\n{context}\n"

        from agent.core import Agent
        sub_agent = Agent(
            provider_name=main_agent.provider_name,
            model=main_agent.model,
            tool_registry=sub_registry,
            system_prompt=sub_sys,
            is_sub_agent=True,
            max_iterations=_SUB_MAX_ITER,
        )

        full_prompt = f"请完成以下任务：\n\n{task}"
        result = await sub_agent.chat(full_prompt)

        content = result.get("content", "(no response)")
        tool_calls = result.get("tool_calls", []) or []

        output_parts = [f"[子任务完成]\n{content}"]
        if tool_calls:
            tool_summary = ", ".join(tc.get("tool", "?") for tc in tool_calls)
            output_parts.append(f"使用了工具: {tool_summary}")

        return "\n\n".join(output_parts)

    except Exception as e:
        return f"[子任务失败] {e}"
