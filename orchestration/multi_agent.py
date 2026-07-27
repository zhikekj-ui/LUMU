"""Multi-Agent orchestration system.

Supports:
- Agent Swarm: 多个 Agent 并行/串行协作完成任务
- Router Agent: 意图识别后路由到专门 Agent
- Supervisor Agent: 监督和协调子 Agent
- Handoff: Agent 之间传递上下文和中间结果
"""

import asyncio
import json
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Optional
from datetime import datetime, timezone

from agent.core import Agent
from tools.registry import ToolRegistry


@dataclass
class AgentRole:
    """Defines a specialized agent role."""
    name: str
    description: str
    system_prompt: str
    model: str = ""  # 可以指定不同的模型
    provider: str = ""  # 可以指定不同的供应商
    tools: list[str] = field(default_factory=list)  # 可以限制可用工具子集
    max_turns: int = 10
    temperature: float = 0.7


@dataclass
class AgentMessage:
    """A message in the multi-agent conversation."""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    role: str = "user"
    content: str = ""
    agent_name: str = ""
    metadata: dict = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class AgentResult:
    """Result from an agent execution."""
    agent_name: str
    content: str
    tool_calls: list[dict] = field(default_factory=list)
    tokens_used: int = 0
    turns: int = 0
    success: bool = True


class AgentSwarm:
    """Multi-agent swarm orchestration.
    
    Multiple agents work in parallel or sequentially on subtasks.
    The supervisor collects results and synthesizes a final response.
    """
    
    def __init__(self, tool_registry: ToolRegistry):
        self.tool_registry = tool_registry
        self.agents: dict[str, Agent] = {}
        self.history: list[AgentMessage] = []
    
    def register_agent(self, role: AgentRole):
        """Register a specialized agent."""
        agent = Agent(
            provider_name=role.provider or None,
            model=role.model or None,
            tool_registry=self.tool_registry,
        )
        # Override system prompt if provided
        if role.system_prompt:
            agent._custom_system_prompt = role.system_prompt
        self.agents[role.name] = {
            "agent": agent,
            "role": role,
        }
    
    async def execute_parallel(self, task: str, agent_names: list[str], 
                                 context: str = "") -> list[AgentResult]:
        """Execute multiple agents in parallel on the same task."""
        tasks = []
        for name in agent_names:
            if name in self.agents:
                tasks.append(self._run_agent(name, task, context))
        if not tasks:
            return []
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return [r for r in results if isinstance(r, AgentResult)]
    
    async def execute_sequential(self, task: str, agent_names: list[str],
                                  context: str = "") -> AgentResult:
        """Execute agents sequentially, each receiving previous agent's output."""
        current_context = context
        last_result = None
        for name in agent_names:
            if name in self.agents:
                last_result = await self._run_agent(name, task, current_context)
                current_context = f"Previous agent '{last_result.agent_name}' said:\n{last_result.content}"
                self.history.append(AgentMessage(
                    role="agent",
                    content=last_result.content,
                    agent_name=last_result.agent_name,
                ))
        return last_result
    
    async def _run_agent(self, name: str, task: str, context: str = "") -> AgentResult:
        """Run a single agent on a task."""
        agent_info = self.agents[name]
        agent = agent_info["agent"]
        role = agent_info["role"]
        
        full_prompt = task
        if context:
            full_prompt = f"{task}\n\nContext:\n{context}"
        
        try:
            result = await agent.chat(full_prompt)
            return AgentResult(
                agent_name=name,
                content=result.get("content", ""),
                tool_calls=result.get("tool_calls", []),
                tokens_used=result.get("tokens_used", 0),
                turns=1,
                success=True,
            )
        except Exception as e:
            return AgentResult(
                agent_name=name,
                content=f"Error: {str(e)}",
                success=False,
            )


class RouterAgent:
    """Intent recognition and routing to specialized agents."""
    
    INTENT_PROMPT = """You are an intent classifier. Analyze the user's message and classify it into one of these categories:

1. **coding** - Programming, debugging, code review, architecture questions
2. **research** - Information lookup, analysis, comparison, fact-checking
3. **creative** - Writing, brainstorming, storytelling, content creation
4. **data** - Data analysis, visualization, statistics, math
5. **system** - Server management, file operations, system commands
6. **conversation** - General chat, small talk, questions about yourself

Respond with ONLY a JSON object:
{"intent": "coding|research|creative|data|system|conversation", "confidence": 0.0-1.0, "reasoning": "brief explanation"}"""
    
    def __init__(self, agent: Agent):
        self.agent = agent
        self.routes: dict[str, str] = {}
    
    def add_route(self, intent: str, agent_name: str):
        """Map an intent to an agent."""
        self.routes[intent] = agent_name
    
    async def classify(self, message: str) -> dict:
        """Classify user intent."""
        result = await self.agent.chat(self.INTENT_PROMPT, session_id="router")
        content = result.get("content", "")
        try:
            # Extract JSON from response
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                content = content.split("```")[1].split("```")[0]
            return json.loads(content.strip())
        except json.JSONDecodeError:
            return {"intent": "conversation", "confidence": 0.5, "reasoning": "Failed to parse"}
    
    async def route(self, message: str) -> Optional[str]:
        """Route message to appropriate agent."""
        classification = await self.classify(message)
        intent = classification.get("intent", "conversation")
        return self.routes.get(intent)
