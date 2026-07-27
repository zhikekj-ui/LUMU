"""Delegate tool — spawn sub-agents for complex task decomposition.

The main agent can call delegate_task to hand off a sub-task to a
specialized sub-agent. The sub-agent runs independently with its own
tool set and returns the result.

Key design decisions:
- Sub-agents share the same provider (no extra API keys needed)
- Sub-agents don't get delegate_task (prevents infinite recursion)
- Max 3 iterations per sub-agent (keeps things bounded)
- Results are returned as text for the main agent to integrate
"""
import asyncio
import uuid


def register(registry):
    registry.register(
        name="delegate_task",
        description=(
            "Delegate a complex sub-task to a specialized sub-agent. "
            "Use when a task benefits from focused attention or a different approach. "
            "The sub-agent runs independently and returns the result."
        ),
        parameters={
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "Clear description of what the sub-agent should do",
                },
                "context": {
                    "type": "string",
                    "description": "Relevant context or background information (optional)",
                },
                "toolsets": {
                    "type": "string",
                    "description": "Comma-separated toolset names to give the sub-agent (e.g. 'file,terminal'). Default: all available.",
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


async def delegate_task(task: str, context: str = "", toolsets: str = "") -> str:
    """Spawn a sub-agent to handle a sub-task."""
    try:
        main_agent = _get_agent()

        # Build tool registry for sub-agent (exclude orchestration tools to prevent recursion)
        from tools.registry import ToolRegistry
        sub_registry = ToolRegistry()

        # Determine which toolsets to include
        allowed_toolsets = None
        if toolsets:
            allowed_toolsets = set(t.strip() for t in toolsets.split(","))
        else:
            # All toolsets except orchestration
            all_toolsets = set(main_agent.tools.list_toolsets().keys())
            allowed_toolsets = all_toolsets - {"orchestration"}

        # Copy tools from main registry (excluding orchestration)
        for tool in main_agent.tools.list_tools(allowed_toolsets):
            if tool.name == "delegate_task":
                continue  # Never give sub-agents the delegate tool
            sub_registry.register(
                name=tool.name,
                description=tool.description,
                parameters=tool.parameters,
                handler=tool.handler,
                toolset=tool.toolset,
                is_async=tool.is_async,
                emoji=tool.emoji,
            )

        # Build system prompt for sub-agent
        from agent.prompts import build_system_prompt
        tool_names = [t.name for t in sub_registry.list_tools()]
        system_prompt = build_system_prompt(
            agent_name="LUMU AI (子任务)",
            tool_names=tool_names,
        )
        if context:
            system_prompt += f"\n\n任务背景：\n{context}"

        # Create sub-agent (shares provider with main agent)
        from agent.core import Agent
        sub_agent = Agent(
            provider_name=main_agent.provider_name,
            model=main_agent.model,
            tool_registry=sub_registry,
            system_prompt=system_prompt,
            is_sub_agent=True,
        )

        # Run the task with limited iterations
        full_prompt = f"请完成以下任务：\n\n{task}"
        result = await sub_agent.chat(full_prompt)

        # Format result
        content = result.get("content", "(no response)")
        tool_calls = result.get("tool_calls", [])

        output_parts = [f"[子任务完成]\n{content}"]
        if tool_calls:
            tool_summary = ", ".join(tc["tool"] for tc in tool_calls)
            output_parts.append(f"使用了工具: {tool_summary}")

        return "\n\n".join(output_parts)

    except Exception as e:
        return f"[子任务失败] {e}"
