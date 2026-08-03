"""Context profile — lightweight structured memory of who the user is and what they work on.

Automatically extracted from conversations, injected into system prompt.
This is the foundation for world model: user profile, project profile, system profile.
"""
import json
import os
import time
from typing import Optional


class ContextProfile:
    """Manages a JSON-based context profile that evolves with every conversation."""

    def __init__(self, profile_path: str):
        self.path = profile_path
        self.data = self._load()

    def _load(self) -> dict:
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {
            "user": {},
            "projects": [],
            "systems": [],
            "common_tasks": [],
            "recent_topics": [],
            "session_history": [],
            "proactive_insights": [],
            "last_updated": None,
        }

    def save(self):
        self.data["last_updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

    def update_from_llm(self, extracted: dict):
        """Smart-merge LLM-extracted profile data into existing profile."""
        if not extracted or not isinstance(extracted, dict):
            return

        changed = False

        # --- User profile (scalar fields: overwrite) ---
        user = extracted.get("user", {})
        if user:
            for key in ("name", "role", "expertise", "communication_style", "language"):
                if user.get(key):
                    old_val = self.data["user"].get(key)
                    new_val = user[key]
                    if isinstance(new_val, list):
                        # Merge lists, deduplicate
                        existing = set(old_val) if isinstance(old_val, list) else set()
                        existing.update(new_val)
                        self.data["user"][key] = list(existing)
                    else:
                        if old_val != new_val:
                            self.data["user"][key] = new_val
                            changed = True

        # --- Projects (list: merge by name) ---
        projects = extracted.get("projects", [])
        if projects:
            existing_names = {p.get("name", "") for p in self.data["projects"]}
            for proj in projects:
                if isinstance(proj, dict) and proj.get("name"):
                    if proj["name"] not in existing_names:
                        self.data["projects"].append(proj)
                        existing_names.add(proj["name"])
                        changed = True
                    else:
                        # Update existing project
                        for p in self.data["projects"]:
                            if p.get("name") == proj["name"]:
                                for k, v in proj.items():
                                    if isinstance(v, list) and isinstance(p.get(k), list):
                                        s = set(p[k])
                                        s.update(v)
                                        p[k] = list(s)
                                    elif v and p.get(k) != v:
                                        p[k] = v
                                        changed = True

        # --- Systems (list: merge by name/address) ---
        systems = extracted.get("systems", [])
        if systems:
            existing_sys = {s.get("name", s.get("address", "")) for s in self.data["systems"]}
            for sys in systems:
                if isinstance(sys, dict):
                    key = sys.get("name", sys.get("address", ""))
                    if key and key not in existing_sys:
                        self.data["systems"].append(sys)
                        existing_sys.add(key)
                        changed = True

        # --- Common tasks (list: deduplicate, keep max 20) ---
        tasks = extracted.get("common_tasks", [])
        if tasks:
            existing_tasks = set(self.data["common_tasks"])
            for t in tasks:
                if t and t not in existing_tasks:
                    self.data["common_tasks"].append(t)
                    existing_tasks.add(t)
                    changed = True
            # Keep last 20
            if len(self.data["common_tasks"]) > 20:
                self.data["common_tasks"] = self.data["common_tasks"][-20:]

        # --- Recent topics (list: replace, keep last 5) ---
        topics = extracted.get("recent_topics", [])
        if topics:
            for t in topics:
                if t:
                    # Remove if already present, then add at end
                    if t in self.data["recent_topics"]:
                        self.data["recent_topics"].remove(t)
                    self.data["recent_topics"].append(t)
            self.data["recent_topics"] = self.data["recent_topics"][-5:]
            changed = True

        if changed:
            self.save()

    def add_session_summary(self, timestamp: str, topic: str, summary: str,
                            pending: list = None, next_steps: str = ""):
        """Add a session handoff summary. Keep last 5."""
        if "session_history" not in self.data:
            self.data["session_history"] = []
        entry = {
            "timestamp": timestamp,
            "topic": topic,
            "summary": summary,
            "pending": pending or [],
            "next_steps": next_steps,
        }
        self.data["session_history"].append(entry)
        self.data["session_history"] = self.data["session_history"][-5:]
        self.save()

    def add_insight(self, insight: str, category: str = "observation"):
        """Add a proactive insight. Keep last 5, deduplicate."""
        if "proactive_insights" not in self.data:
            self.data["proactive_insights"] = []
        # Deduplicate
        for existing in self.data["proactive_insights"]:
            if existing.get("insight") == insight:
                return
        entry = {
            "insight": insight,
            "category": category,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        self.data["proactive_insights"].append(entry)
        self.data["proactive_insights"] = self.data["proactive_insights"][-5:]
        self.save()

    def to_prompt(self) -> Optional[str]:
        """Convert profile to a concise system prompt string. Returns None if empty."""
        parts = []

        # User profile
        u = self.data.get("user", {})
        if u:
            user_parts = []
            if u.get("name"):
                user_parts.append(f"姓名: {u['name']}")
            if u.get("role"):
                user_parts.append(f"角色: {u['role']}")
            if u.get("expertise"):
                user_parts.append(f"专业领域: {', '.join(u['expertise'][:5])}")
            if u.get("communication_style"):
                user_parts.append(f"沟通偏好: {u['communication_style']}")
            if user_parts:
                parts.append("用户画像:\n" + "\n".join(f"  - {p}" for p in user_parts))

        # Projects
        projects = self.data.get("projects", [])
        if projects:
            proj_lines = []
            for p in projects[-5:]:
                line = p.get("name", "")
                if p.get("technologies"):
                    line += f" (技术: {', '.join(p['technologies'][:4])})"
                if p.get("status"):
                    line += f" [{p['status']}]"
                proj_lines.append(f"  - {line}")
            parts.append("用户项目:\n" + "\n".join(proj_lines))

        # Systems
        systems = self.data.get("systems", [])
        if systems:
            sys_lines = []
            for s in systems[-5:]:
                line = s.get("name", s.get("address", ""))
                if s.get("type"):
                    line += f" ({s['type']})"
                if s.get("address"):
                    line += f" @ {s['address']}"
                if s.get("details"):
                    line += f" — {s['details'][:60]}"
                sys_lines.append(f"  - {line}")
            parts.append("用户系统:\n" + "\n".join(sys_lines))

        # Common tasks
        tasks = self.data.get("common_tasks", [])
        if tasks:
            parts.append("常见任务: " + ", ".join(tasks[:5]))

        # Recent topics
        topics = self.data.get("recent_topics", [])
        if topics:
            parts.append("近期话题: " + " → ".join(topics))

        # Session history (last 3)
        sessions = self.data.get("session_history", [])
        if sessions:
            sess_lines = []
            for s in sessions[-3:]:
                ts = s.get("timestamp", "")[:10]  # date only
                topic = s.get("topic", "")
                summ = s.get("summary", "")[:120]
                line = f"  - [{ts}] {topic} — {summ}"
                pending = s.get("pending", [])
                if pending:
                    line += f" (待办: {'; '.join(pending[:3])})"
                ns = s.get("next_steps", "")
                if ns:
                    line += f" → 下次: {ns[:80]}"
                sess_lines.append(line)
            parts.append("最近对话记录:\n" + "\n".join(sess_lines))

        # Proactive insights (v9)
        insights = self.data.get("proactive_insights", [])
        if insights:
            ins_lines = []
            for i in insights[-3:]:
                ins_lines.append(f"  - {i.get('insight', '')}")
            parts.append("主动观察:\n" + "\n".join(ins_lines))

        if not parts:
            return None

        return "以下是关于当前用户的上下文信息，请据此个性化你的回答：\n\n" + "\n\n".join(parts)

    def stats(self) -> dict:
        return {
            "user_fields": len(self.data.get("user", {})),
            "projects": len(self.data.get("projects", [])),
            "systems": len(self.data.get("systems", [])),
            "common_tasks": len(self.data.get("common_tasks", [])),
            "recent_topics": len(self.data.get("recent_topics", [])),
            "session_history": len(self.data.get("session_history", [])),
            "proactive_insights": len(self.data.get("proactive_insights", [])),
            "last_updated": self.data.get("last_updated"),
        }
