"""Skill tools — let the agent save, recall, and execute reusable skills/procedures."""


def register(registry):
    registry.register(
        name="skill_save",
        description="Save a reusable skill/procedure. Use when you complete a complex task and want to remember how to do it next time.",
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Short name for this skill (e.g. 'deploy_flask_app')"},
                "description": {"type": "string", "description": "What this skill does and when to use it"},
                "content": {"type": "string", "description": "Step-by-step instructions in markdown"},
                "tags": {"type": "string", "description": "Comma-separated tags (e.g. 'deploy,flask,python')"},
            },
            "required": ["name", "description", "content"],
        },
        handler=save_skill,
        toolset="skills",
        emoji="📚",
    )
    registry.register(
        name="skill_search",
        description="Search for a relevant skill before starting a complex task.",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to search for"},
                "limit": {"type": "integer", "description": "Max results (default 5)"},
            },
            "required": ["query"],
        },
        handler=search_skill,
        toolset="skills",
        emoji="🔍",
    )
    registry.register(
        name="skill_get",
        description="Get the full instructions of a saved skill by name.",
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "The skill name"},
            },
            "required": ["name"],
        },
        handler=get_skill,
        toolset="skills",
        emoji="📖",
    )
    registry.register(
        name="skill_list",
        description="List all saved skills.",
        parameters={
            "type": "object",
            "properties": {
                "tag": {"type": "string", "description": "Filter by tag (optional)"},
            },
        },
        handler=list_skills,
        toolset="skills",
        emoji="📋",
    )
    registry.register(
        name="skill_delete",
        description="Delete a saved skill.",
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "The skill name to delete"},
            },
            "required": ["name"],
        },
        handler=delete_skill,
        toolset="skills",
        emoji="🗑️",
    )


def _get_skill_manager():
    from agent.core import _agent_instance
    return _agent_instance.skills


def save_skill(name: str, description: str, content: str, tags: str = "") -> str:
    try:
        sm = _get_skill_manager()
        is_new = sm.save(name, description, content, tags)
        action = "Created" if is_new else "Updated"
        return f"{action} skill: {name}"
    except Exception as e:
        return f"Error saving skill: {e}"


def search_skill(query: str, limit: int = 5) -> str:
    try:
        sm = _get_skill_manager()
        results = sm.search(query, limit)
        if not results:
            return f"No skills found for: {query}"
        lines = []
        for r in results:
            tags = f" [{r['tags']}]" if r["tags"] else ""
            lines.append(f"- {r['name']}: {r['description']}{tags} (used {r['use_count']}x)")
        return "\n".join(lines)
    except Exception as e:
        return f"Error searching skills: {e}"


def get_skill(name: str) -> str:
    try:
        sm = _get_skill_manager()
        skill = sm.get(name)
        if not skill:
            return f"Skill not found: {name}"
        sm.increment_use(name)
        return f"## {skill['name']}\n\n{skill['description']}\n\n---\n\n{skill['content']}"
    except Exception as e:
        return f"Error getting skill: {e}"


def list_skills(tag: str = "") -> str:
    try:
        sm = _get_skill_manager()
        results = sm.list_all(tag if tag else "")
        if not results:
            return "(no skills saved)"
        lines = []
        for r in results:
            tags = f" [{r['tags']}]" if r["tags"] else ""
            lines.append(f"- {r['name']}: {r['description']}{tags} (used {r['use_count']}x)")
        return "\n".join(lines)
    except Exception as e:
        return f"Error listing skills: {e}"


def delete_skill(name: str) -> str:
    try:
        sm = _get_skill_manager()
        if sm.delete(name):
            return f"Deleted skill: {name}"
        return f"Skill not found: {name}"
    except Exception as e:
        return f"Error deleting skill: {e}"
