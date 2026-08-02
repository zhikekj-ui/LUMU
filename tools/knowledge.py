"""Knowledge base tools — persistent structured knowledge storage and retrieval."""
import os
from pathlib import Path
from tools.registry import ToolRegistry


def _get_kb():
    """Lazy-init knowledge base."""
    from knowledge.base import KnowledgeBase
    db_path = os.path.join(os.getenv("AGENT_HOME", str(Path(__file__).resolve().parent.parent)), "data", "knowledge.db")
    return KnowledgeBase(db_path=db_path)


def handle_kb_add(**kwargs):
    """Add a knowledge entry to the knowledge base.
    
    Args:
        title: Entry title
        content: Entry content (full text)
        category: Category (default: 'general')
        tags: List of tags (JSON array or comma-separated)
        source: Source identifier
        metadata: Optional JSON metadata
    """
    import json
    
    title = kwargs.get("title", "")
    content = kwargs.get("content", "")
    category = kwargs.get("category", "general")
    tags = kwargs.get("tags", [])
    source = kwargs.get("source", "")
    metadata = kwargs.get("metadata", {})
    
    if isinstance(tags, str):
        try:
            tags = json.loads(tags)
        except Exception:
            tags = [t.strip() for t in tags.split(",") if t.strip()]
    
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except Exception:
            metadata = {}
    
    if not title or not content:
        return {"error": "Title and content are required"}
    
    try:
        kb = _get_kb()
        result = kb.add(
            title=title,
            content=content,
            category=category,
            tags=tags,
            source=source,
            metadata=metadata,
        )
        return result
    except Exception as e:
        return {"error": str(e)}


def handle_kb_search(**kwargs):
    """Search the knowledge base using hybrid keyword + vector search.
    
    Args:
        query: Search query
        limit: Max results (default: 10)
        category: Filter by category
        tags: Filter by tags (JSON array or comma-separated)
    """
    import json
    
    query = kwargs.get("query", "")
    limit = kwargs.get("limit", 10)
    category = kwargs.get("category", "")
    tags = kwargs.get("tags", "")
    
    if isinstance(tags, str) and tags:
        try:
            tags = json.loads(tags)
        except Exception:
            tags = [t.strip() for t in tags.split(",") if t.strip()]
    else:
        tags = None
    
    if not query.strip():
        return {"error": "Query is empty"}
    
    try:
        kb = _get_kb()
        results = kb.search(query, limit=limit, category=category if category else None, tags=tags)
        
        # Truncate content for response
        for r in results:
            if len(r.get("content", "")) > 500:
                r["content_preview"] = r["content"][:500] + "..."
            else:
                r["content_preview"] = r["content"]
        
        return {
            "results": results,
            "total": len(results),
            "query": query,
        }
    except Exception as e:
        return {"error": str(e)}


def handle_kb_get(**kwargs):
    """Get a specific knowledge entry by ID.
    
    Args:
        entry_id: The knowledge entry ID
    """
    entry_id = kwargs.get("entry_id", "")
    if not entry_id:
        return {"error": "Entry ID required"}
    
    try:
        kb = _get_kb()
        entry = kb.get(entry_id)
        if not entry:
            return {"error": f"Entry '{entry_id}' not found"}
        return entry
    except Exception as e:
        return {"error": str(e)}


def handle_kb_update(**kwargs):
    """Update an existing knowledge entry.
    
    Args:
        entry_id: Entry ID to update
        title: New title (optional)
        content: New content (optional)
        category: New category (optional)
        tags: New tags (optional)
    """
    import json
    
    entry_id = kwargs.get("entry_id", "")
    title = kwargs.get("title")
    content = kwargs.get("content")
    category = kwargs.get("category")
    tags = kwargs.get("tags")
    
    if isinstance(tags, str):
        try:
            tags = json.loads(tags)
        except Exception:
            tags = [t.strip() for t in tags.split(",") if t.strip()]
    
    if not entry_id:
        return {"error": "Entry ID required"}
    
    try:
        kb = _get_kb()
        result = kb.update(entry_id, title=title, content=content, category=category, tags=tags)
        return result
    except Exception as e:
        return {"error": str(e)}


def handle_kb_delete(**kwargs):
    """Delete a knowledge entry.
    
    Args:
        entry_id: Entry ID to delete
    """
    entry_id = kwargs.get("entry_id", "")
    if not entry_id:
        return {"error": "Entry ID required"}
    
    try:
        kb = _get_kb()
        return kb.delete(entry_id)
    except Exception as e:
        return {"error": str(e)}


def handle_kb_list(**kwargs):
    """List knowledge entries, optionally filtered by category."""
    category = kwargs.get("category", "")
    limit = kwargs.get("limit", 50)
    
    try:
        kb = _get_kb()
        entries = kb.list_entries(category=category if category else None, limit=limit)
        categories = kb.list_categories()
        stats = kb.stats()
        
        return {
            "entries": entries,
            "categories": categories,
            "stats": stats,
        }
    except Exception as e:
        return {"error": str(e)}


def handle_kb_stats(**kwargs):
    """Get knowledge base statistics."""
    try:
        kb = _get_kb()
        return kb.stats()
    except Exception as e:
        return {"error": str(e)}



def handle_kb_reembed(**kwargs):
    """Re-embed all knowledge entries using the current embedding method.
    
    Use after changing embedding API configuration to upgrade all vectors.
    """
    try:
        kb = _get_kb()
        result = kb.reembed_all()
        from knowledge.embedding import get_embedding_info
        result["embedding_info"] = get_embedding_info()
        return result
    except Exception as e:
        return {"error": str(e)}


def register(registry: ToolRegistry):
    """Register knowledge base tools."""
    registry.register(
        name="kb_add",
        description="向知识库添加一条知识条目。支持分类、标签、来源标记。自动进行向量化索引。",
        handler=handle_kb_add,
        toolset="knowledge",
        parameters={
            "title": {"type": "string", "description": "标题", "required": True},
            "content": {"type": "string", "description": "内容", "required": True},
            "category": {"type": "string", "description": "分类（默认general）", "required": False},
            "tags": {"type": "string", "description": "标签（JSON数组或逗号分隔）", "required": False},
            "source": {"type": "string", "description": "来源", "required": False},
            "metadata": {"type": "string", "description": "JSON元数据", "required": False},
        },
    )
    
    registry.register(
        name="kb_search",
        description="混合搜索知识库（关键词+向量语义）。返回最相关的知识条目。",
        handler=handle_kb_search,
        toolset="knowledge",
        parameters={
            "query": {"type": "string", "description": "搜索查询", "required": True},
            "limit": {"type": "integer", "description": "最大结果数（默认10）", "required": False},
            "category": {"type": "string", "description": "按分类过滤", "required": False},
            "tags": {"type": "string", "description": "按标签过滤", "required": False},
        },
    )
    
    registry.register(
        name="kb_get",
        description="通过ID获取知识库条目的完整内容。",
        handler=handle_kb_get,
        toolset="knowledge",
        parameters={
            "entry_id": {"type": "string", "description": "条目ID", "required": True},
        },
    )
    
    registry.register(
        name="kb_update",
        description="更新知识库中的条目。可更新标题、内容、分类、标签。",
        handler=handle_kb_update,
        toolset="knowledge",
        parameters={
            "entry_id": {"type": "string", "description": "条目ID", "required": True},
            "title": {"type": "string", "description": "新标题", "required": False},
            "content": {"type": "string", "description": "新内容", "required": False},
            "category": {"type": "string", "description": "新分类", "required": False},
            "tags": {"type": "string", "description": "新标签", "required": False},
        },
    )
    
    registry.register(
        name="kb_delete",
        description="删除知识库中的指定条目。",
        handler=handle_kb_delete,
        toolset="knowledge",
        parameters={
            "entry_id": {"type": "string", "description": "条目ID", "required": True},
        },
    )
    
    registry.register(
        name="kb_list",
        description="列出知识库条目，可按分类过滤。同时返回分类列表和统计信息。",
        handler=handle_kb_list,
        toolset="knowledge",
        parameters={
            "category": {"type": "string", "description": "按分类过滤", "required": False},
            "limit": {"type": "integer", "description": "最大条目数（默认50）", "required": False},
        },
    )
    
    registry.register(
        name="kb_stats",
        description="获取知识库统计信息（总条目数、分类数等）。",
        handler=handle_kb_stats,
        toolset="knowledge",
        parameters={},
    )

    registry.register(
        name="kb_reembed",
        description="用当前embedding方法重新向量化所有知识条目。切换embedding API后使用。",
        handler=handle_kb_reembed,
        toolset="knowledge",
        parameters={},
    )

