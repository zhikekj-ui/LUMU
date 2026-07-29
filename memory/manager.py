"""Simple SQLite-based memory manager."""
import json
import sqlite3
from pathlib import Path
from datetime import datetime, timezone


class MemoryManager:
    """Persistent memory using SQLite (from Hermes Agent hermes_state)."""

    def __init__(self, db_path: str = "data/memory.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    key TEXT UNIQUE NOT NULL,
                    content TEXT NOT NULL,
                    category TEXT DEFAULT 'general',
                    created_at TEXT DEFAULT (datetime('now')),
                    updated_at TEXT DEFAULT (datetime('now'))
                )
            """)
            conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(key, content)
            """)
            # Space isolation column (idempotent — safe on existing DBs)
            try:
                conn.execute("ALTER TABLE memories ADD COLUMN space TEXT DEFAULT 'work'")
            except sqlite3.OperationalError:
                pass

    def save(self, key: str, content: str, category: str = "general", space: str = "work"):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """INSERT INTO memories (key, content, category, space)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(key) DO UPDATE SET content=excluded.content, space=excluded.space, updated_at=datetime('now')""",
                (key, content, category, space),
            )
            # Update FTS
            conn.execute("DELETE FROM memories_fts WHERE key=?", (key,))
            conn.execute("INSERT INTO memories_fts (key, content) VALUES (?, ?)", (key, content))

    def recall(self, key: str) -> str | None:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute("SELECT content FROM memories WHERE key=?", (key,)).fetchone()
            return row[0] if row else None

    def search(self, query: str, limit: int = 5, space: str | None = None) -> list[dict]:
        with sqlite3.connect(self.db_path) as conn:
            # Try FTS5 first (works for English/single-word queries)
            try:
                if space:
                    rows = conn.execute(
                        """SELECT m.key, m.content, m.category FROM memories_fts f
                           JOIN memories m ON m.key = f.key
                           WHERE memories_fts MATCH ? AND m.space=? LIMIT ?""",
                        (query, space, limit),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        """SELECT m.key, m.content, m.category FROM memories_fts f
                           JOIN memories m ON m.key = f.key
                           WHERE memories_fts MATCH ? LIMIT ?""",
                        (query, limit),
                    ).fetchall()
                if rows:
                    return [{"key": r[0], "content": r[1], "category": r[2]} for r in rows]
            except Exception:
                pass
            # Fallback: split query into terms, LIKE search each, combine results
            terms = [t.strip() for t in query.split() if len(t.strip()) >= 2]
            if not terms:
                terms = [query]
            seen_keys = set()
            results = []
            for term in terms:
                rows = conn.execute(
                    """SELECT key, content, category, space FROM memories
                       WHERE content LIKE ? OR key LIKE ?
                       ORDER BY updated_at DESC""",
                    (f"%{term}%", f"%{term}%"),
                ).fetchall()
                for r in rows:
                    if space and r[3] != space:
                        continue
                    if r[0] not in seen_keys:
                        seen_keys.add(r[0])
                        results.append({"key": r[0], "content": r[1], "category": r[2]})
            return results[:limit]

    def recall_relevant(self, query: str, top_k: int = 5, category: str | None = None, space: str | None = None) -> list[dict]:
        """Recall memories relevant to the current query.

        Uses keyword matching + recency scoring for relevance ranking.
        Combines FTS5 search with temporal decay for better results.
        """
        query_lower = query.lower()
        stop_words = {"the", "a", "an", "is", "are", "was", "were", "to", "of",
                       "and", "or", "in", "for", "on", "with", "at", "by", "from",
                       "this", "that", "it", "as", "be", "has", "have", "had", "not",
                       "but", "if", "so", "no", "do", "can", "will", "my", "me", "i",
                       "you", "he", "she", "we", "they", "what", "how", "why", "when",
                       "where", "which", "who", "all", "any", "each", "every", "both"}
        keywords = set(query_lower.split()) - stop_words
        # Also extract CJK characters as keywords
        cjk_chars = re.findall(r'[一-鿿]{2,}', query_lower)
        keywords.update(cjk_chars)

        if not keywords:
            keywords = {query_lower}

        with sqlite3.connect(self.db_path) as conn:
            all_rows = conn.execute(
                "SELECT key, content, category, space, updated_at FROM memories ORDER BY updated_at DESC"
            ).fetchall()

        scored = []
        for key, content_text, cat, sp, updated_at in all_rows:
            if space and sp != space:
                continue
            if category and cat != category:
                continue
            content_lower = content_text.lower()

            # Score: keyword overlap
            overlap = len(keywords & set(content_lower.split()))
            # Also check CJK keywords in content
            for kw in cjk_chars:
                if kw in content_lower:
                    overlap += 2

            if overlap == 0 and key.lower() not in query_lower:
                continue

            # Recency scoring with decay over 90 days
            try:
                days_ago = (datetime.now(timezone.utc) - datetime.fromisoformat(updated_at.replace("Z", "+00:00"))).days
            except Exception:
                days_ago = 30
            recency_score = max(0, 1 - days_ago / 90)
            score = (overlap * 2 + 1) * recency_score
            if score > 0:
                scored.append({
                    "key": key,
                    "content": content_text,
                    "category": cat,
                    "score": round(score, 2),
                })

        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:top_k]

    def list_all(self, category: str | None = None, space: str | None = None) -> list[dict]:
        with sqlite3.connect(self.db_path) as conn:
            if category and space:
                rows = conn.execute(
                    "SELECT key, content, category, created_at FROM memories WHERE category=? AND space=? ORDER BY updated_at DESC",
                    (category, space),
                ).fetchall()
            elif category:
                rows = conn.execute(
                    "SELECT key, content, category, created_at FROM memories WHERE category=? ORDER BY updated_at DESC",
                    (category,),
                ).fetchall()
            elif space:
                rows = conn.execute(
                    "SELECT key, content, category, created_at FROM memories WHERE space=? ORDER BY updated_at DESC",
                    (space,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT key, content, category, created_at FROM memories ORDER BY updated_at DESC"
                ).fetchall()
            return [{"key": r[0], "content": r[1], "category": r[2], "created_at": r[3]} for r in rows]

    def delete(self, key: str):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM memories WHERE key=?", (key,))
            conn.execute("DELETE FROM memories_fts WHERE key=?", (key,))
