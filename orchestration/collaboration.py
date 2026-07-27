"""Multi-agent collaboration — team-based task execution with multiple LLM agents.

Provides:
- AgentPool: manage a pool of specialized agents with role-specific prompts
- CollaborativeTask: execute tasks in parallel, sequential, or debate mode
- MessageBus: in-memory message passing between agents
- Registered tools: collab_create_team, collab_execute, collab_send_message, collab_team_status

Sub-agents are lightweight LLM wrappers (direct AsyncOpenAI calls) to avoid
the recursion and overhead of full Agent instances.
"""
import asyncio
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from openai import AsyncOpenAI

from providers.registry import get as get_provider


# ---------------------------------------------------------------------------
# Internal helpers — lightweight LLM call (no full Agent instance)
# ---------------------------------------------------------------------------

def _get_client_and_model() -> tuple[AsyncOpenAI, str]:
    """Build an AsyncOpenAI client from the default provider and return (client, model)."""
    import config
    provider = get_provider(config.DEFAULT_PROVIDER)
    if provider is None:
        raise RuntimeError(
            f"Provider '{config.DEFAULT_PROVIDER}' not found. "
            "Call providers.registry.discover_providers() first."
        )
    api_key = os.getenv(provider.api_key_env, "")
    client = AsyncOpenAI(api_key=api_key, base_url=provider.base_url)
    model = provider.models[0] if provider.models else config.DEFAULT_MODEL
    return client, model


async def _llm_call(system_prompt: str, user_message: str, temperature: float = 0.7) -> str:
    """Single-shot LLM call with a system prompt and user message."""
    client, model = _get_client_and_model()
    response = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        temperature=temperature,
        max_tokens=16000,
    )
    return (response.choices[0].message.content or "").strip()


# ---------------------------------------------------------------------------
# AgentPool — manages named, role-specialized agents
# ---------------------------------------------------------------------------

@dataclass
class PoolAgent:
    """A lightweight agent entry in the pool."""
    name: str
    role: str
    system_prompt: str
    allowed_tools: list[str] = field(default_factory=list)


class AgentPool:
    """In-memory pool of specialized agents.

    Each agent is just a (name, role, system_prompt, allowed_tools) record —
    no persistent state, no full Agent instance.  The LLM is called directly
    via _llm_call with the agent's system prompt.
    """

    def __init__(self):
        self._agents: dict[str, PoolAgent] = {}

    def create_agent(
        self,
        name: str,
        role: str,
        system_prompt: str = "",
        allowed_tools: list[str] | None = None,
    ) -> PoolAgent:
        if name in self._agents:
            raise ValueError(f"Agent '{name}' already exists in the pool")
        agent = PoolAgent(
            name=name,
            role=role,
            system_prompt=system_prompt or f"You are a {role}. Respond concisely and helpfully.",
            allowed_tools=allowed_tools or [],
        )
        self._agents[name] = agent
        return agent

    def remove_agent(self, name: str) -> bool:
        return self._agents.pop(name, None) is not None

    def get_agent(self, name: str) -> PoolAgent | None:
        return self._agents.get(name)

    def list_agents(self) -> list[PoolAgent]:
        return list(self._agents.values())

    async def ask(self, name: str, message: str, temperature: float = 0.7) -> str:
        """Send a message to a pool agent and get its response."""
        agent = self._agents.get(name)
        if agent is None:
            raise KeyError(f"Agent '{name}' not found in pool")
        return await _llm_call(agent.system_prompt, message, temperature=temperature)


# ---------------------------------------------------------------------------
# MessageBus — simple in-memory message passing
# ---------------------------------------------------------------------------

@dataclass
class Message:
    from_agent: str
    to_agent: str
    content: str
    timestamp: float = field(default_factory=time.time)
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])


class MessageBus:
    """In-memory message queues for inter-agent communication."""

    def __init__(self):
        self._queues: dict[str, list[Message]] = {}
        self._history: dict[str, list[Message]] = {}

    def send(self, from_agent: str, to_agent: str, message: str) -> Message:
        msg = Message(from_agent=from_agent, to_agent=to_agent, content=message)
        self._queues.setdefault(to_agent, []).append(msg)
        # History is kept for both sender and receiver
        self._history.setdefault(from_agent, []).append(msg)
        self._history.setdefault(to_agent, []).append(msg)
        return msg

    def receive(self, agent_name: str) -> list[Message]:
        """Drain and return all pending messages for an agent."""
        msgs = self._queues.pop(agent_name, [])
        return msgs

    def broadcast(self, from_agent: str, message: str, recipients: list[str] | None = None) -> list[Message]:
        """Send a message to all known agents (or a specific recipient list)."""
        sent: list[Message] = []
        for name in (recipients or list(self._queues.keys())):
            if name == from_agent:
                continue
            sent.append(self.send(from_agent, name, message))
        return sent

    def get_history(self, agent_name: str) -> list[Message]:
        return list(self._history.get(agent_name, []))


# ---------------------------------------------------------------------------
# CollaborativeTask — parallel / sequential / debate execution
# ---------------------------------------------------------------------------

class CollaborativeTask:
    """Execute a task using multiple agents from a pool.

    Modes:
      parallel   — all agents work independently; results are merged.
      sequential — agents work in a pipeline; each sees the previous output.
      debate     — agents take turns responding to each other (max 3 rounds),
                   then the last round of outputs is merged.
    """

    DEBATE_ROUNDS = 3

    def __init__(self, pool: AgentPool, bus: MessageBus | None = None):
        self.pool = pool
        self.bus = bus or MessageBus()

    async def execute(
        self,
        task_description: str,
        agents: list[str],
        mode: str = "parallel",
        shared_context: str = "",
    ) -> dict[str, Any]:
        """Run a collaborative task.

        Args:
            task_description: what needs to be done.
            agents: list of agent names from the pool.
            mode: "parallel", "sequential", or "debate".
            shared_context: optional background info available to all agents.

        Returns:
            dict with keys: mode, results (dict[name -> str]), summary (str).
        """
        if not agents:
            return {"mode": mode, "results": {}, "summary": "No agents provided."}

        # Validate that all agents exist
        for name in agents:
            if self.pool.get_agent(name) is None:
                return {
                    "mode": mode,
                    "results": {},
                    "summary": f"Error: agent '{name}' not found in pool.",
                }

        context_block = f"\n\nBackground context:\n{shared_context}" if shared_context else ""

        if mode == "parallel":
            results = await self._run_parallel(task_description, agents, context_block)
        elif mode == "sequential":
            results = await self._run_sequential(task_description, agents, context_block)
        elif mode == "debate":
            results = await self._run_debate(task_description, agents, context_block)
        else:
            return {
                "mode": mode,
                "results": {},
                "summary": f"Unknown mode '{mode}'. Use parallel, sequential, or debate.",
            }

        summary = self._merge_results(results, mode)
        return {"mode": mode, "results": results, "summary": summary}

    # --- mode implementations ---

    async def _run_parallel(
        self, task: str, agents: list[str], context: str
    ) -> dict[str, str]:
        """All agents work independently via asyncio.gather."""

        async def _work(name: str) -> tuple[str, str]:
            prompt = f"Task:\n{task}{context}\n\nProvide your analysis as {self.pool.get_agent(name).role}."
            try:
                resp = await self.pool.ask(name, prompt)
                self.bus.send("system", name, f"Parallel task assigned: {task[:80]}")
                return name, resp
            except Exception as e:
                return name, f"[Error from {name}]: {e}"

        pairs = await asyncio.gather(*[_work(n) for n in agents])
        return dict(pairs)

    async def _run_sequential(
        self, task: str, agents: list[str], context: str
    ) -> dict[str, str]:
        """Chain outputs: each agent sees the previous agent's response."""
        results: dict[str, str] = {}
        running_context = context

        for name in agents:
            chain_history = "\n".join(
                f"[{n}]: {r}" for n, r in results.items()
            )
            extra = f"\n\nPrevious work in the pipeline:\n{chain_history}" if chain_history else ""
            prompt = (
                f"Task:\n{task}{running_context}{extra}\n\n"
                f"Build on the previous work and provide your contribution as "
                f"{self.pool.get_agent(name).role}."
            )
            try:
                resp = await self.pool.ask(name, prompt)
            except Exception as e:
                resp = f"[Error from {name}]: {e}"
            results[name] = resp
            # Notify via bus
            if len(results) > 1:
                prev_name = list(results.keys())[-2]
                self.bus.send(prev_name, name, f"Sequential handoff: see my output above.")

        return results

    async def _run_debate(
        self, task: str, agents: list[str], context: str
    ) -> dict[str, str]:
        """Agents take turns responding to each other for DEBATE_ROUNDS rounds."""
        # Each agent's latest statement
        statements: dict[str, str] = {}

        for round_num in range(1, self.DEBATE_ROUNDS + 1):
            for name in agents:
                others_text = "\n".join(
                    f"[{n}] says: {s}" for n, s in statements.items() if n != name
                )
                round_instruction = (
                    f"This is debate round {round_num}/{self.DEBATE_ROUNDS}."
                )
                if round_num == 1:
                    base_prompt = f"Topic:\n{task}{context}\n\n{round_instruction}"
                else:
                    base_prompt = (
                        f"Topic:\n{task}{context}\n\n{round_instruction}\n\n"
                        f"Other agents' positions:\n{others_text}\n\n"
                        f"Respond to their points, refine your position, or find common ground."
                    )
                prompt = (
                    f"{base_prompt}\n\n"
                    f"Provide your response as {self.pool.get_agent(name).role}."
                )
                try:
                    resp = await self.pool.ask(name, prompt, temperature=0.8)
                except Exception as e:
                    resp = f"[Error from {name}]: {e}"
                statements[name] = resp

                # Broadcast via bus so other agents can see
                for other in agents:
                    if other != name:
                        self.bus.send(name, other, f"Round {round_num}: {resp[:200]}")

        return statements

    # --- result merging ---

    @staticmethod
    def _merge_results(results: dict[str, str], mode: str) -> str:
        parts: list[str] = []
        for name, text in results.items():
            parts.append(f"--- {name} ---\n{text}")
        header = f"[{mode.upper()} collaboration — {len(results)} agent(s)]"
        return header + "\n" + "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Module-level singletons (one pool + bus per registered team)
# ---------------------------------------------------------------------------

_teams: dict[str, dict[str, Any]] = {}
# Each entry: { "pool": AgentPool, "bus": MessageBus, "task": CollaborativeTask, "created_at": float }


def _get_team(team_name: str) -> dict[str, Any] | None:
    return _teams.get(team_name)


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------

async def collab_create_team(team_config: list[dict]) -> str:
    """Create a team of specialized agents.

    team_config is a list of dicts, each with:
      - name (str): unique agent name
      - role (str): the agent's role / specialty
      - system_prompt (str, optional): custom system prompt
      - allowed_tools (list[str], optional): tool name restrictions
    """
    if not team_config:
        return "Error: team_config is empty. Provide at least one agent."

    team_name = f"team_{uuid.uuid4().hex[:8]}"
    pool = AgentPool()
    bus = MessageBus()
    task = CollaborativeTask(pool, bus)

    created: list[str] = []
    errors: list[str] = []

    for entry in team_config:
        name = entry.get("name", "").strip()
        role = entry.get("role", "").strip()
        if not name:
            errors.append("Skipped an entry with missing 'name'.")
            continue
        if not role:
            errors.append(f"Skipped '{name}': missing 'role'.")
            continue
        try:
            pool.create_agent(
                name=name,
                role=role,
                system_prompt=entry.get("system_prompt", ""),
                allowed_tools=entry.get("allowed_tools", []),
            )
            created.append(name)
        except ValueError as e:
            errors.append(str(e))

    if not created:
        return f"Error: no agents were created. {'; '.join(errors)}"

    _teams[team_name] = {
        "pool": pool,
        "bus": bus,
        "task": task,
        "created_at": time.time(),
    }

    lines = [f"Team '{team_name}' created with {len(created)} agent(s):"]
    for agent in pool.list_agents():
        lines.append(f"  - {agent.name} ({agent.role})")
    if errors:
        lines.append(f"Warnings: {'; '.join(errors)}")
    return "\n".join(lines)


async def collab_execute(task: str, team_name: str, mode: str = "parallel") -> str:
    """Execute a task using a previously created team.

    Args:
        task: description of what the team should do.
        team_name: name returned by collab_create_team.
        mode: "parallel", "sequential", or "debate".
    """
    team = _get_team(team_name)
    if team is None:
        return f"Error: team '{team_name}' not found. Create it first with collab_create_team."

    collab_task: CollaborativeTask = team["task"]
    pool: AgentPool = team["pool"]
    agent_names = [a.name for a in pool.list_agents()]

    if not agent_names:
        return f"Error: team '{team_name}' has no agents."

    try:
        result = await collab_task.execute(
            task_description=task,
            agents=agent_names,
            mode=mode,
        )
        return result["summary"]
    except Exception as e:
        return f"Error during collaborative execution: {e}"


async def collab_send_message(from_agent: str, to_agent: str, message: str) -> str:
    """Send a message from one agent to another within a team.

    The receiving agent will process the message on its next interaction.
    This is mainly useful for inspecting message history via collab_team_status.
    """
    # Find which team both agents belong to
    for tname, team in _teams.items():
        pool: AgentPool = team["pool"]
        bus: MessageBus = team["bus"]
        if pool.get_agent(from_agent) and pool.get_agent(to_agent):
            msg = bus.send(from_agent, to_agent, message)
            return f"Message sent in team '{tname}': [{from_agent}] -> [{to_agent}] (id={msg.id})"

    return f"Error: could not find a team containing both '{from_agent}' and '{to_agent}'."


async def collab_team_status(team_name: str) -> str:
    """Get the status of a team: its agents and recent message activity."""
    team = _get_team(team_name)
    if team is None:
        return f"Error: team '{team_name}' not found."

    pool: AgentPool = team["pool"]
    bus: MessageBus = team["bus"]

    lines = [f"Team: {team_name}"]
    lines.append(f"Agents ({len(pool.list_agents())}):")
    for agent in pool.list_agents():
        tool_info = f", tools: {', '.join(agent.allowed_tools)}" if agent.allowed_tools else ""
        lines.append(f"  - {agent.name} ({agent.role}{tool_info})")

    # Collect message counts and recent messages
    all_agents = [a.name for a in pool.list_agents()]
    total_messages = 0
    recent: list[str] = []
    for name in all_agents:
        history = bus.get_history(name)
        total_messages += len(history)
        for msg in history[-3:]:  # last 3 per agent
            recent.append(f"  [{msg.from_agent} -> {msg.to_agent}] {msg.content[:120]}")

    lines.append(f"\nMessages: {total_messages} total")
    if recent:
        lines.append("Recent activity:")
        # Deduplicate (messages appear in both sender and receiver history)
        seen: set[str] = set()
        for line in recent:
            if line not in seen:
                seen.add(line)
                lines.append(line)
    else:
        lines.append("No messages exchanged yet.")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool registration (called by AST-based discovery)
# ---------------------------------------------------------------------------

def register(registry):
    registry.register(
        name="collab_create_team",
        description=(
            "Create a team of specialized agents for collaborative task execution. "
            "Each agent has a name, role, and optional custom system prompt. "
            "Returns a team_name to use with collab_execute."
        ),
        parameters={
            "type": "object",
            "properties": {
                "team_config": {
                    "type": "array",
                    "description": "List of agent configurations. Each item: {name, role, system_prompt?, allowed_tools?}",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "description": "Unique agent name"},
                            "role": {"type": "string", "description": "Agent role / specialty"},
                            "system_prompt": {"type": "string", "description": "Custom system prompt (optional)"},
                            "allowed_tools": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Allowed tool names (optional)",
                            },
                        },
                        "required": ["name", "role"],
                    },
                },
            },
            "required": ["team_config"],
        },
        handler=collab_create_team,
        is_async=True,
        toolset="orchestration",
        emoji="👥",
    )

    registry.register(
        name="collab_execute",
        description=(
            "Execute a task with a previously created team of agents. "
            "Modes: parallel (all agents work independently), "
            "sequential (pipeline — each agent builds on the previous), "
            "debate (agents discuss and converge over 3 rounds)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "Description of the task for the team",
                },
                "team_name": {
                    "type": "string",
                    "description": "Team name returned by collab_create_team",
                },
                "mode": {
                    "type": "string",
                    "enum": ["parallel", "sequential", "debate"],
                    "description": "Collaboration mode (default: parallel)",
                },
            },
            "required": ["task", "team_name"],
        },
        handler=collab_execute,
        is_async=True,
        toolset="orchestration",
        emoji="🚀",
    )

    registry.register(
        name="collab_send_message",
        description=(
            "Send a message between two agents in the same team. "
            "Useful for directing inter-agent communication or inspecting "
            "message flow via collab_team_status."
        ),
        parameters={
            "type": "object",
            "properties": {
                "from_agent": {
                    "type": "string",
                    "description": "Name of the sending agent",
                },
                "to_agent": {
                    "type": "string",
                    "description": "Name of the receiving agent",
                },
                "message": {
                    "type": "string",
                    "description": "Message content",
                },
            },
            "required": ["from_agent", "to_agent", "message"],
        },
        handler=collab_send_message,
        is_async=True,
        toolset="orchestration",
        emoji="💬",
    )

    registry.register(
        name="collab_team_status",
        description=(
            "Get the status of a team: list of agents, their roles, "
            "and recent message activity."
        ),
        parameters={
            "type": "object",
            "properties": {
                "team_name": {
                    "type": "string",
                    "description": "Team name returned by collab_create_team",
                },
            },
            "required": ["team_name"],
        },
        handler=collab_team_status,
        is_async=True,
        toolset="orchestration",
        emoji="📊",
    )
