"""Capability introspection tool — lets the agent see its own full surface.

Answers the question "what can I do / what is my environment" at runtime,
so the model never operates on a stale, hardcoded picture of its own
capabilities (no cognitive disconnect). Aggregates: registered tools,
toolsets, file-based skill packs, saved skills, configured providers/models,
exposure policy, and backend API routes.
"""
import json


def _get_agent():
    from agent.core import _agent_instance
    return _agent_instance


def register(registry):
    registry.register(
        name="introspect_capabilities",
        description=(
            "Return a live manifest of EVERYTHING you can do right now: registered tools, "
            "toolsets, file-based skill packs (SKILL.md), saved skills, configured providers "
            "and their enabled models, the tool-exposure policy, and all backend API routes. "
            "Call this when you are unsure whether a capability exists, when the user asks what "
            "you can do, or before attempting a task that may need an extension."
        ),
        parameters={"type": "object", "properties": {}},
        handler=introspect_capabilities,
        toolset="skills",
        emoji="🧭",
    )


def introspect_capabilities() -> str:
    try:
        agent = _get_agent()

        tools = [t.name for t in agent.tools.list_tools()]
        toolsets = agent.tools.list_toolsets()

        from skills.skill_packs import scan_packs
        packs = [
            {
                "name": p.get("name"),
                "description": p.get("description"),
                "always": p.get("always"),
                "triggers": p.get("triggers"),
            }
            for p in scan_packs()
        ]

        saved = agent.skills.list_all()

        from core.user_config import load_config
        cfg = load_config()
        providers = {
            pid: {
                "configured": bool(pc.get("api_key")),
                "enabled_models": pc.get("enabled_models", []),
            }
            for pid, pc in (cfg.get("providers") or {}).items()
        }

        from tools.exposure import exposure_policy
        policy = exposure_policy()

        routes = []
        try:
            import main as _main
            routes = sorted({getattr(r, "path", "") for r in _main.app.routes if getattr(r, "path", "")})
        except Exception:
            routes = []

        manifest = {
            "tool_count": len(tools),
            "tools": tools,
            "toolsets": toolsets,
            "skill_packs": packs,
            "saved_skills": saved,
            "providers": providers,
            "exposure_policy": policy,
            "api_routes": routes,
        }
        return json.dumps(manifest, ensure_ascii=False, indent=2)
    except Exception as e:
        return f"Error introspecting capabilities: {e}"
