"""Memory tools — let the agent save and recall information across sessions."""


def register(registry):
    registry.register(
        name="memory_save",
        description="Save a piece of information to long-term memory. Use when the user shares something important to remember.",
        parameters={
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "Short identifier for this memory (e.g. 'user_preference_language')",
                },
                "content": {
                    "type": "string",
                    "description": "The information to remember",
                },
                "category": {
                    "type": "string",
                    "description": "Category: general, preference, fact, task, person",
                },
            },
            "required": ["key", "content"],
        },
        handler=save_memory,
        toolset="memory",
        emoji="🧠",
    )
    registry.register(
        name="memory_search",
        description="Search long-term memory for relevant information.",
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "What to search for",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results (default 5)",
                },
            },
            "required": ["query"],
        },
        handler=search_memory,
        toolset="memory",
        emoji="🔍",
    )
    registry.register(
        name="memory_list",
        description="List all saved memories, optionally filtered by category.",
        parameters={
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": "Filter by category (optional)",
                },
            },
        },
        handler=list_memories,
        toolset="memory",
        emoji="📋",
    )
    registry.register(
        name="memory_delete",
        description="Delete a specific memory by its key.",
        parameters={
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "The memory key to delete",
                },
            },
            "required": ["key"],
        },
        handler=delete_memory,
        toolset="memory",
        emoji="🗑️",
    )


# Lazy import to avoid circular dependency
def _get_memory_manager():
    from agent.core import _agent_instance
    return _agent_instance.memory


def save_memory(key: str, content: str, category: str = "general", space: str | None = None) -> str:
    try:
        mm = _get_memory_manager()
        # 未显式指定空间时，按当前对话所属空间标注（默认 work）
        if space is None:
            try:
                space = getattr(_agent_instance, "_current_space", "work")
            except Exception:
                space = "work"
        mm.save(key, content, category, space=space)
        return f"Saved memory: [{category}] {key}"
    except Exception as e:
        return f"Error saving memory: {e}"


def search_memory(query: str, limit: int = 5) -> str:
    try:
        mm = _get_memory_manager()
        results = mm.search(query, limit)
        if not results:
            return f"No memories found for: {query}"
        lines = []
        for r in results:
            lines.append(f"[{r['category']}] {r['key']}: {r['content']}")
        return "\n".join(lines)
    except Exception as e:
        return f"Error searching memory: {e}"


def list_memories(category: str = "") -> str:
    try:
        mm = _get_memory_manager()
        results = mm.list_all(category if category else None)
        if not results:
            return "(no memories saved)"
        lines = []
        for r in results:
            lines.append(f"[{r['category']}] {r['key']}: {r['content']}")
        return "\n".join(lines)
    except Exception as e:
        return f"Error listing memories: {e}"


def delete_memory(key: str) -> str:
    try:
        mm = _get_memory_manager()
        mm.delete(key)
        return f"Deleted memory: {key}"
    except Exception as e:
        return f"Error deleting memory: {e}"
