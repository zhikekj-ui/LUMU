"""Skill manager — persistent storage for reusable procedures/skills.

Skills are step-by-step workflows the agent can save and reuse.
Stored in SQLite with FTS5 for search.
"""
import sqlite3
from pathlib import Path
from datetime import datetime


class SkillManager:
    """Manage skills: save, list, search, get, delete."""

    def __init__(self, db_path: str = "data/skills.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS skills (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    description TEXT NOT NULL,
                    content TEXT NOT NULL,
                    tags TEXT DEFAULT '',
                    created_at TEXT DEFAULT (datetime('now')),
                    updated_at TEXT DEFAULT (datetime('now')),
                    use_count INTEGER DEFAULT 0
                )
            """)
            conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS skills_fts USING fts5(name, description, content, tags)
            """)

    def save(self, name: str, description: str, content: str, tags: str = "") -> bool:
        """Save or update a skill. Returns True if new, False if updated."""
        with sqlite3.connect(self.db_path) as conn:
            existing = conn.execute("SELECT id FROM skills WHERE name=?", (name,)).fetchone()
            if existing:
                conn.execute(
                    """UPDATE skills SET description=?, content=?, tags=?, updated_at=datetime('now')
                       WHERE name=?""",
                    (description, content, tags, name),
                )
                conn.execute("DELETE FROM skills_fts WHERE name=?", (name,))
                conn.execute("INSERT INTO skills_fts (name, description, content, tags) VALUES (?, ?, ?, ?)",
                             (name, description, content, tags))
                return False
            else:
                conn.execute(
                    """INSERT INTO skills (name, description, content, tags)
                       VALUES (?, ?, ?, ?)""",
                    (name, description, content, tags),
                )
                conn.execute("INSERT INTO skills_fts (name, description, content, tags) VALUES (?, ?, ?, ?)",
                             (name, description, content, tags))
                return True

    def get(self, name: str) -> dict | None:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT name, description, content, tags, created_at, updated_at, use_count FROM skills WHERE name=?",
                (name,),
            ).fetchone()
            if not row:
                return None
            return {
                "name": row[0], "description": row[1], "content": row[2],
                "tags": row[3], "created_at": row[4], "updated_at": row[5],
                "use_count": row[6],
            }

    def list_all(self, tag: str = "") -> list[dict]:
        with sqlite3.connect(self.db_path) as conn:
            if tag:
                rows = conn.execute(
                    "SELECT name, description, tags, use_count, updated_at FROM skills WHERE tags LIKE ? ORDER BY use_count DESC",
                    (f"%{tag}%",),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT name, description, tags, use_count, updated_at FROM skills ORDER BY use_count DESC"
                ).fetchall()
            return [
                {"name": r[0], "description": r[1], "tags": r[2], "use_count": r[3], "updated_at": r[4]}
                for r in rows
            ]

    def search(self, query: str, limit: int = 5) -> list[dict]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT name, description, tags, use_count FROM skills_fts WHERE skills_fts MATCH ? LIMIT ?",
                (query, limit),
            ).fetchall()
            return [{"name": r[0], "description": r[1], "tags": r[2], "use_count": r[3]} for r in rows]

    def increment_use(self, name: str):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("UPDATE skills SET use_count = use_count + 1 WHERE name=?", (name,))

    def delete(self, name: str) -> bool:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("DELETE FROM skills WHERE name=?", (name,))
            conn.execute("DELETE FROM skills_fts WHERE name=?", (name,))
            return cursor.rowcount > 0
