"""Advanced reasoning strategies for improved intelligence.

Implements:
- Chain of Thought (CoT): Step-by-step reasoning
- ReAct: Reasoning + Acting loop
- Self-Reflection: Agent evaluates and improves its own output
- Plan-and-Execute: Decompose complex tasks then execute
"""

import json
from typing import Optional


COT_PROMPT = """Before answering, think through this step by step:
1. Understand what the user is asking
2. Break down the problem into parts
3. Consider multiple approaches
4. Choose the best approach and explain your reasoning
5. Provide a clear, actionable answer

Think step by step:"""

REACT_PROMPT = """You are an agent that can use tools to solve problems. For each step:
1. **Thought**: Analyze the current situation and decide what to do
2. **Action**: Use a tool or respond to the user
3. **Observation**: Process the result of your action

Continue this Thought-Action-Observation loop until the task is complete."""

SELF_REFLECTION_PROMPT = """After providing your answer, critically evaluate it:
1. Does it directly address the user's question?
2. Are there any gaps or assumptions?
3. Could there be a better approach?
4. Rate your confidence (1-10)

If your confidence is below 7, revise your answer."""

PLAN_EXECUTE_PROMPT = """For complex tasks, first create a plan:

## Plan
1. [Step 1 description]
2. [Step 2 description]
3. [Step 3 description]
...

Then execute each step methodically. Mark each step as done with [x] as you complete it."""


class ReasoningStrategy:
    """Manages reasoning strategy selection and prompt injection."""
    
    STRATEGIES = {
        "chain_of_thought": {"prompt": COT_PROMPT, "description": "Step-by-step reasoning for complex problems"},
        "react": {"prompt": REACT_PROMPT, "description": "Reasoning + Acting for tasks requiring tools"},
        "self_reflection": {"prompt": SELF_REFLECTION_PROMPT, "description": "Self-evaluation for critical tasks"},
        "plan_execute": {"prompt": PLAN_EXECUTE_PROMPT, "description": "Task decomposition for multi-step goals"},
        "default": {"prompt": "", "description": "Standard response without extra reasoning"},
    }
    
    @classmethod
    def get_strategy(cls, message: str) -> str:
        """Auto-detect the best reasoning strategy based on message content."""
        msg_lower = message.lower()
        
        # Complex reasoning needed
        complex_keywords = ["explain", "why", "how does", "analyze", "compare", "evaluate",
                          "what if", "design", "architect", "optimize", "debug", "fix"]
        if any(kw in msg_lower for kw in complex_keywords):
            if any(kw in msg_lower for kw in ["step by step", "break down", "plan", "multiple steps"]):
                return "plan_execute"
            return "chain_of_thought"
        
        # Tool-using tasks
        tool_keywords = ["search", "find", "look up", "check", "read", "write", "create",
                        "install", "deploy", "run", "execute", "file", "server", "code"]
        if any(kw in msg_lower for kw in tool_keywords):
            return "react"
        
        # Critical tasks
        critical_keywords = ["important", "critical", "ensure", "verify", "security",
                          "production", "deploy", "migrate", "production-grade"]
        if any(kw in msg_lower for kw in critical_keywords):
            return "self_reflection"
        
        return "default"
    
    @classmethod
    def inject_prompt(cls, message: str, strategy: Optional[str] = None) -> str:
        """Inject reasoning strategy prompt into the message."""
        if strategy is None:
            strategy = cls.get_strategy(message)
        
        strat_info = cls.STRATEGIES.get(strategy, cls.STRATEGIES["default"])
        if strat_info["prompt"]:
            return f"{strat_info['prompt']}\n\nUser request:\n{message}"
        return message
