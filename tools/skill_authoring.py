"""Skill authoring tool — let the agent extend itself by writing hot-loaded skill packs.

A skill pack is a SKILL.md file under skills/packs/<name>/. Once written it is
hot-reloaded (mtime cache) and immediately becomes part of the agent's own
system prompt: its name+description appear in the skill index, and its full
content auto-injects when the user message matches its triggers (or always:true).

This is the durable self-extension path: capabilities authored here are
remembered across sessions without touching core code. Writes are sandboxed to
skills/packs/ only (the core registry already blocks agent/api/providers).
"""
import os
import re
from pathlib import Path


def register(registry):
    registry.register(
        name="skill_pack_write",
        description=(
            "Create or update a hot-loaded SKILL.md skill pack under skills/packs/<name>/. "
            "The pack becomes immediately available to you: its name+description show in the "
            "system-prompt skill index, and its full content auto-injects when the user message "
            "matches its triggers (or always:true). Use this to give yourself a NEW durable "
            "capability or procedure — it persists across sessions and does not modify core code. "
            "Write the instructions clearly, as if writing a runbook for yourself."
        ),
        parameters={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Pack name (alphanumeric, dash, underscore). Used as the folder name under skills/packs/.",
                },
                "description": {
                    "type": "string",
                    "description": "One-line description shown in the skill index.",
                },
                "content": {
                    "type": "string",
                    "description": "Full instructions / markdown body for the skill (step-by-step runbook).",
                },
                "triggers": {
                    "type": "string",
                    "description": "Comma-separated trigger keywords that expand the pack into context when matched in the user message. Leave empty if always:true.",
                },
                "always": {
                    "type": "boolean",
                    "description": "If true, the pack is always injected into context. Default false.",
                },
            },
            "required": ["name", "description", "content"],
        },
        handler=write_skill_pack,
        toolset="skills",
        emoji="✍️",
    )


def write_skill_pack(name: str, description: str, content: str, triggers: str = "", always: bool = False) -> str:
    if not re.match(r"^[A-Za-z0-9_-]+$", name or ""):
        return "⛔ 技能名仅允许字母、数字、中划线、下划线"

    base = Path(os.getenv("AGENT_HOME", str(Path(__file__).resolve().parent.parent)))
    packs_root = (base / "skills" / "packs").resolve()
    pdir = (packs_root / name).resolve()

    # Sandbox guard: the resolved path MUST stay under skills/packs/
    try:
        pdir.relative_to(packs_root)
    except Exception:
        return "⛔ 只能写入 skills/packs/ 目录（核心代码受写保护）"

    pdir.mkdir(parents=True, exist_ok=True)

    fm = ["---", f"name: {name}", f"description: {description}"]
    if triggers:
        fm.append(f"triggers: {triggers}")
    fm.append(f"always: {str(bool(always)).lower()}")
    fm.append("---")

    text = "\n".join(fm) + "\n\n" + content.strip() + "\n"
    (pdir / "SKILL.md").write_text(text, encoding="utf-8")
    return f"✅ 已创建/更新技能包：skills/packs/{name}/SKILL.md（热加载，下次对话即生效）"
