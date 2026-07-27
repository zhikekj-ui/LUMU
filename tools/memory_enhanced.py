"""Enhanced memory tools — semantic search + episodic memory access.

Extends the original memory tools with:
- Semantic similarity search (by meaning, not just keywords)
- Episodic event recording and retrieval
- Memory statistics and management
"""


def register(registry):
    registry.register(
        name="memory_semantic_search",
        description=(
            "语义搜索长期记忆：根据含义而非关键词查找记忆。"
            "例如搜索'用户的编程偏好'可以找到相关的偏好记忆，即使没有精确的关键词匹配。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "用自然语言描述你要找什么信息",
                },
                "limit": {
                    "type": "integer",
                    "description": "最大返回数量（默认5）",
                },
                "category": {
                    "type": "string",
                    "description": "可选：限定搜索类别（general/preference/fact/task/person）",
                },
            },
            "required": ["query"],
        },
        handler=semantic_search,
        toolset="memory",
        emoji="🧠",
    )
    registry.register(
        name="memory_record_event",
        description=(
            "记录一个情景事件到长期记忆。用于记住重要的对话里程碑、"
            "用户决策、任务完成情况等。事件可按语义搜索。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "event_type": {
                    "type": "string",
                    "description": "事件类型：decision(决策), milestone(里程碑), error(错误), preference(偏好), task_complete(任务完成)",
                },
                "description": {
                    "type": "string",
                    "description": "事件描述",
                },
                "details": {
                    "type": "string",
                    "description": "详细信息（可选）",
                },
                "importance": {
                    "type": "number",
                    "description": "重要性 0.0-1.0（默认0.3，重要事件用0.7+）",
                },
            },
            "required": ["event_type", "description"],
        },
        handler=record_event,
        toolset="memory",
        emoji="📝",
    )
    registry.register(
        name="memory_search_events",
        description="搜索历史事件记录，按语义相似度排序。",
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索什么事件",
                },
                "limit": {
                    "type": "integer",
                    "description": "最大返回数量（默认5）",
                },
                "event_type": {
                    "type": "string",
                    "description": "可选：限定事件类型",
                },
            },
            "required": ["query"],
        },
        handler=search_events,
        toolset="memory",
        emoji="🔍",
    )
    registry.register(
        name="memory_stats",
        description="查看记忆系统的统计信息：记忆数量、分类分布、情景事件数等。",
        parameters={
            "type": "object",
            "properties": {},
        },
        handler=memory_stats,
        toolset="memory",
        emoji="📊",
    )


def _get_semantic_memory():
    """Lazy-init semantic memory singleton."""
    global _semantic_mem
    if _semantic_mem is None:
        from memory.semantic import SemanticMemory
        _semantic_mem = SemanticMemory()
    return _semantic_mem


_semantic_mem = None


def semantic_search(query: str, limit: int = 5, category: str = "") -> str:
    try:
        mem = _get_semantic_memory()
        results = mem.search(query, limit, category if category else None)
        if not results:
            return f"未找到与 '{query}' 相关的记忆"
        lines = []
        for r in results:
            lines.append(
                f"[{r['category']}] {r['key']}: {r['content']} "
                f"(相关度: {r['score']:.2f})"
            )
        return "\n".join(lines)
    except Exception as e:
        return f"语义搜索失败: {e}"


def record_event(event_type: str, description: str, 
                 details: str = "", importance: float = 0.3) -> str:
    try:
        mem = _get_semantic_memory()
        mem.record_event(event_type, description, details, importance=importance)
        return f"已记录事件 [{event_type}]: {description}"
    except Exception as e:
        return f"记录事件失败: {e}"


def search_events(query: str, limit: int = 5, event_type: str = "") -> str:
    try:
        mem = _get_semantic_memory()
        results = mem.search_events(query, limit, event_type if event_type else None)
        if not results:
            return f"未找到与 '{query}' 相关的事件"
        lines = []
        for r in results:
            lines.append(
                f"[{r['event_type']}] {r['description']} "
                f"(相关度: {r['score']:.2f}, {r['created_at']})"
            )
            if r.get("details"):
                lines.append(f"  详情: {r['details'][:200]}")
        return "\n".join(lines)
    except Exception as e:
        return f"搜索事件失败: {e}"


def memory_stats() -> str:
    try:
        mem = _get_semantic_memory()
        stats = mem.get_stats()
        lines = [
            f"语义记忆: {stats['semantic_count']} 条",
            f"分类分布: {', '.join(f'{k}={v}' for k, v in stats['categories'].items()) or '无'}",
            f"情景事件: {stats['episodic_count']} 条",
        ]
        return "\n".join(lines)
    except Exception as e:
        return f"获取统计失败: {e}"
