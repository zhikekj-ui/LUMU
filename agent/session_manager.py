"""Persistent session state management with SQLite backend.

Provides enhanced session tracking, task management, and full-text search
across session history. Backward-compatible with JSON-based session files
from storage/session_store.py — on first use, existing JSON sessions are
imported into the SQLite database automatically.

Classes:
    SessionState   — single session's in-memory representation
    SessionManager — SQLite-backed CRUD + FTS5 search
    TaskTracker    — hierarchical task tracking across sessions

Tools registered under the "session" toolset:
    session_list, session_resume, session_search,
    task_create, task_update, task_list
"""

import json
import os
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _resolve_db_path() -> str:
    """Return the absolute path for the SQLite database, honouring AGENT_BASE_DIR."""
    base = os.environ.get("AGENT_BASE_DIR", "data")
    db_dir = Path(base)
    db_dir.mkdir(parents=True, exist_ok=True)
    return str(db_dir / "sessions.db")


def _resolve_json_sessions_dir() -> Path:
    """Return the directory where legacy JSON session files live."""
    base = os.environ.get("AGENT_BASE_DIR", "data")
    return Path(base) / "sessions"


# ---------------------------------------------------------------------------
# SessionState
# ---------------------------------------------------------------------------

class SessionState:
    """In-memory representation of a single session's persistent state.

    Attributes are kept plain so the object is trivially serialisable for
    API responses via ``to_dict()``.
    """

    def __init__(
        self,
        session_id: Optional[str] = None,
        title: Optional[str] = None,
        created_at: Optional[str] = None,
        updated_at: Optional[str] = None,
    ):
        self.session_id: str = session_id or str(uuid.uuid4())
        now = _utcnow()
        self.created_at: str = created_at or now
        self.updated_at: str = updated_at or now
        self.title: Optional[str] = title
        self.messages: List[Dict[str, Any]] = []
        self.context_summary: Optional[str] = None
        self.active_tasks: List[Dict[str, Any]] = []
        self.metadata: Dict[str, Any] = {}

    # -- message helpers ----------------------------------------------------

    def add_message(
        self,
        role: str,
        content: str,
        tool_calls: Optional[List[dict]] = None,
        timestamp: Optional[str] = None,
    ) -> dict:
        """Append a message and return it."""
        msg: Dict[str, Any] = {
            "role": role,
            "content": content,
            "tool_calls": tool_calls or [],
            "timestamp": timestamp or _utcnow(),
        }
        self.messages.append(msg)
        self.updated_at = msg["timestamp"]

        # Auto-generate title from first user message.
        if self.title is None and role == "user" and content:
            snippet = content.strip().replace("\n", " ")
            self.title = snippet[:80] if len(snippet) <= 80 else snippet[:77] + "..."

        return msg

    def get_recent_messages(self, n: int = 20) -> List[dict]:
        """Return the last *n* messages."""
        return self.messages[-n:]

    def get_full_context(self) -> dict:
        """Return everything needed to reconstruct the conversation context."""
        return {
            "session_id": self.session_id,
            "title": self.title,
            "context_summary": self.context_summary,
            "messages": list(self.messages),
            "metadata": dict(self.metadata),
        }

    # -- task helpers -------------------------------------------------------

    def update_task(self, task_id: str, **fields: Any) -> Optional[dict]:
        """Update fields of an active task in-place. Returns the task or None."""
        for task in self.active_tasks:
            if task.get("id") == task_id:
                task.update(fields)
                task["updated_at"] = _utcnow()
                return task
        return None

    def get_active_tasks(self) -> List[dict]:
        return [t for t in self.active_tasks if t.get("status") in ("pending", "in_progress")]

    # -- metadata -----------------------------------------------------------

    def set_metadata(self, key: str, value: Any) -> None:
        self.metadata[key] = value

    # -- serialisation ------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "title": self.title,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "messages": list(self.messages),
            "context_summary": self.context_summary,
            "active_tasks": list(self.active_tasks),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SessionState":
        s = cls(
            session_id=data.get("session_id"),
            title=data.get("title"),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
        )
        s.messages = data.get("messages", [])
        s.context_summary = data.get("context_summary")
        s.active_tasks = data.get("active_tasks", [])
        s.metadata = data.get("metadata", {})
        return s


# ---------------------------------------------------------------------------
# SessionManager  (SQLite)
# ---------------------------------------------------------------------------

_SCHEMA = """\
CREATE TABLE IF NOT EXISTS sessions (
    id          TEXT PRIMARY KEY,
    title       TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    role        TEXT NOT NULL,
    content     TEXT NOT NULL,
    tool_calls_json TEXT NOT NULL DEFAULT '[]',
    timestamp   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, timestamp);

CREATE TABLE IF NOT EXISTS tasks (
    id              TEXT PRIMARY KEY,
    session_id      TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    description     TEXT NOT NULL DEFAULT '',
    status          TEXT NOT NULL DEFAULT 'pending',
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    result          TEXT,
    parent_task_id  TEXT REFERENCES tasks(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_tasks_session ON tasks(session_id);
CREATE INDEX IF NOT EXISTS idx_tasks_status  ON tasks(status);
"""

_FTS_SCHEMA = """\
CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    session_id UNINDEXED,
    role       UNINDEXED,
    content,
    content='messages',
    content_rowid='id'
);

-- Keep FTS in sync via triggers.
CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages BEGIN
    INSERT INTO messages_fts(rowid, session_id, role, content)
    VALUES (new.id, new.session_id, new.role, new.content);
END;

CREATE TRIGGER IF NOT EXISTS messages_ad AFTER DELETE ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, session_id, role, content)
    VALUES ('delete', old.id, old.session_id, old.role, old.content);
END;

CREATE TRIGGER IF NOT EXISTS messages_au AFTER UPDATE ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, session_id, role, content)
    VALUES ('delete', old.id, old.session_id, old.role, old.content);
    INSERT INTO messages_fts(rowid, session_id, role, content)
    VALUES (new.id, new.session_id, new.role, new.content);
END;
"""


class SessionManager:
    """Thread-safe SQLite-backed session store.

    The database is created lazily on first access.  If the database does not
    yet exist, legacy JSON session files are imported automatically.
    """

    def __init__(self, db_path: Optional[str] = None):
        self._db_path = db_path or _resolve_db_path()
        self._lock = threading.Lock()
        self._local = threading.local()
        self._imported_legacy = False
        self._ensure_schema()

    # -- connection management (one conn per thread) -------------------------

    def _conn(self) -> sqlite3.Connection:
        conn: Optional[sqlite3.Connection] = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self._db_path, timeout=10)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.row_factory = sqlite3.Row
            self._local.conn = conn
        return conn

    def _ensure_schema(self) -> None:
        is_new = not Path(self._db_path).exists()
        with self._lock:
            conn = self._conn()
            conn.executescript(_SCHEMA)
            # FTS5 may not be available in every SQLite build; degrade gracefully.
            try:
                conn.executescript(_FTS_SCHEMA)
            except sqlite3.OperationalError:
                pass  # FTS5 not compiled in — search will be unavailable
            conn.commit()
            if is_new and not self._imported_legacy:
                self._imported_legacy = True
                self._import_json_sessions()

    # -- legacy import -------------------------------------------------------

    def _import_json_sessions(self) -> None:
        """Best-effort import of JSON session files written by SessionStore."""
        sessions_dir = _resolve_json_sessions_dir()
        if not sessions_dir.is_dir():
            return
        conn = self._conn()
        for path in sessions_dir.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            sid = data.get("id", path.stem)
            created = data.get("created_at", _utcnow())
            updated = data.get("updated_at", created)
            title = data.get("title")
            meta = json.dumps(data.get("metadata", {}), ensure_ascii=False)
            try:
                conn.execute(
                    "INSERT OR IGNORE INTO sessions (id, title, created_at, updated_at, metadata_json) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (sid, title, created, updated, meta),
                )
                for msg in data.get("messages", []):
                    tc = json.dumps(msg.get("tool_calls", []), ensure_ascii=False)
                    conn.execute(
                        "INSERT INTO messages (session_id, role, content, tool_calls_json, timestamp) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (sid, msg.get("role", "unknown"), msg.get("content", ""), tc,
                         msg.get("timestamp", created)),
                    )
                conn.commit()
            except sqlite3.Error:
                continue

    # -- public API ----------------------------------------------------------

    def create_session(self, title: Optional[str] = None) -> SessionState:
        state = SessionState(title=title)
        meta = json.dumps(state.metadata, ensure_ascii=False)
        with self._lock:
            self._conn().execute(
                "INSERT INTO sessions (id, title, created_at, updated_at, metadata_json) "
                "VALUES (?, ?, ?, ?, ?)",
                (state.session_id, state.title, state.created_at, state.updated_at, meta),
            )
            self._conn().commit()
        return state

    def get_session(self, session_id: str) -> Optional[SessionState]:
        conn = self._conn()
        row = conn.execute(
            "SELECT id, title, created_at, updated_at, metadata_json FROM sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
        if row is None:
            return None
        state = SessionState(
            session_id=row["id"],
            title=row["title"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
        try:
            state.metadata = json.loads(row["metadata_json"])
        except (json.JSONDecodeError, TypeError):
            state.metadata = {}
        # Load messages.
        for m in conn.execute(
            "SELECT role, content, tool_calls_json, timestamp FROM messages "
            "WHERE session_id = ? ORDER BY timestamp",
            (session_id,),
        ):
            try:
                tc = json.loads(m["tool_calls_json"])
            except (json.JSONDecodeError, TypeError):
                tc = []
            state.messages.append({
                "role": m["role"],
                "content": m["content"],
                "tool_calls": tc,
                "timestamp": m["timestamp"],
            })
        # Load active tasks.
        for t in conn.execute(
            "SELECT id, description, status, created_at, updated_at, result, parent_task_id "
            "FROM tasks WHERE session_id = ?",
            (session_id,),
        ):
            state.active_tasks.append({
                "id": t["id"],
                "session_id": session_id,
                "description": t["description"],
                "status": t["status"],
                "created_at": t["created_at"],
                "updated_at": t["updated_at"],
                "result": t["result"],
                "parent_task_id": t["parent_task_id"],
            })
        return state

    def save_session(self, state: SessionState) -> None:
        """Persist the full SessionState (upsert)."""
        meta = json.dumps(state.metadata, ensure_ascii=False)
        with self._lock:
            conn = self._conn()
            conn.execute(
                "INSERT OR REPLACE INTO sessions (id, title, created_at, updated_at, metadata_json) "
                "VALUES (?, ?, ?, ?, ?)",
                (state.session_id, state.title, state.created_at, state.updated_at, meta),
            )
            # Replace all messages for simplicity.
            conn.execute("DELETE FROM messages WHERE session_id = ?", (state.session_id,))
            for msg in state.messages:
                tc = json.dumps(msg.get("tool_calls", []), ensure_ascii=False)
                conn.execute(
                    "INSERT INTO messages (session_id, role, content, tool_calls_json, timestamp) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (state.session_id, msg["role"], msg.get("content", ""), tc,
                     msg.get("timestamp", _utcnow())),
                )
            conn.commit()

    def list_sessions(self, limit: int = 20, offset: int = 0) -> List[dict]:
        conn = self._conn()
        rows = conn.execute(
            "SELECT id, title, created_at, updated_at, metadata_json "
            "FROM sessions ORDER BY updated_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
        results = []
        for r in rows:
            entry = {
                "session_id": r["id"],
                "title": r["title"],
                "created_at": r["created_at"],
                "updated_at": r["updated_at"],
            }
            try:
                entry["metadata"] = json.loads(r["metadata_json"])
            except (json.JSONDecodeError, TypeError):
                entry["metadata"] = {}
            # Attach a short summary from the first user message.
            first = conn.execute(
                "SELECT content FROM messages WHERE session_id = ? AND role = 'user' "
                "ORDER BY timestamp LIMIT 1",
                (r["id"],),
            ).fetchone()
            if first:
                snippet = first["content"].strip().replace("\n", " ")
                entry["summary"] = snippet[:200] if len(snippet) <= 200 else snippet[:197] + "..."
            else:
                entry["summary"] = ""
            results.append(entry)
        return results

    def delete_session(self, session_id: str) -> None:
        with self._lock:
            conn = self._conn()
            conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
            conn.commit()

    def search_sessions(self, query: str, limit: int = 20) -> List[dict]:
        """Full-text search across message content via FTS5.

        Falls back to LIKE search when FTS5 is unavailable.
        """
        conn = self._conn()
        results: List[dict] = []
        try:
            rows = conn.execute(
                "SELECT DISTINCT m.session_id, s.title, s.created_at, s.updated_at, "
                "       snippet(messages_fts, 2, '**', '**', '...', 32) AS snippet "
                "FROM messages_fts f "
                "JOIN messages m ON m.id = f.rowid "
                "JOIN sessions s ON s.id = m.session_id "
                "WHERE messages_fts MATCH ? "
                "ORDER BY rank "
                "LIMIT ?",
                (query, limit),
            ).fetchall()
            for r in rows:
                results.append({
                    "session_id": r["session_id"],
                    "title": r["title"],
                    "updated_at": r["updated_at"],
                    "snippet": r["snippet"],
                })
        except sqlite3.OperationalError:
            # FTS5 not available — fall back to LIKE.
            rows = conn.execute(
                "SELECT DISTINCT m.session_id, s.title, s.updated_at, "
                "       substr(m.content, 1, 200) AS snippet "
                "FROM messages m "
                "JOIN sessions s ON s.id = m.session_id "
                "WHERE m.content LIKE ? "
                "ORDER BY s.updated_at DESC "
                "LIMIT ?",
                (f"%{query}%", limit),
            ).fetchall()
            for r in rows:
                results.append({
                    "session_id": r["session_id"],
                    "title": r["title"],
                    "updated_at": r["updated_at"],
                    "snippet": r["snippet"],
                })
        return results

    def get_active_tasks(self, session_id: Optional[str] = None) -> List[dict]:
        conn = self._conn()
        if session_id:
            rows = conn.execute(
                "SELECT id, session_id, description, status, created_at, updated_at, result, parent_task_id "
                "FROM tasks WHERE session_id = ? AND status IN ('pending', 'in_progress') "
                "ORDER BY created_at",
                (session_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, session_id, description, status, created_at, updated_at, result, parent_task_id "
                "FROM tasks WHERE status IN ('pending', 'in_progress') "
                "ORDER BY created_at"
            ).fetchall()
        return [dict(r) for r in rows]

    def cleanup_old_sessions(self, days: int = 30) -> int:
        """Delete sessions not updated within *days*. Returns count deleted."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        with self._lock:
            conn = self._conn()
            cur = conn.execute(
                "DELETE FROM sessions WHERE updated_at < ?", (cutoff,)
            )
            conn.commit()
            return cur.rowcount


# ---------------------------------------------------------------------------
# TaskTracker
# ---------------------------------------------------------------------------

_VALID_STATUSES = {"pending", "in_progress", "completed", "failed"}


class TaskTracker:
    """Hierarchical task tracking backed by the same SQLite database.

    Tasks can be nested via ``parent_task_id`` to form a tree structure.
    """

    def __init__(self, manager: SessionManager):
        self._manager = manager

    def _conn(self) -> sqlite3.Connection:
        return self._manager._conn()

    def create_task(
        self,
        session_id: str,
        description: str,
        parent_task_id: Optional[str] = None,
    ) -> dict:
        task_id = str(uuid.uuid4())
        now = _utcnow()
        with self._manager._lock:
            self._conn().execute(
                "INSERT INTO tasks (id, session_id, description, status, created_at, updated_at, parent_task_id) "
                "VALUES (?, ?, ?, 'pending', ?, ?, ?)",
                (task_id, session_id, description, now, now, parent_task_id),
            )
            self._conn().commit()
        return {
            "id": task_id,
            "session_id": session_id,
            "description": description,
            "status": "pending",
            "created_at": now,
            "updated_at": now,
            "result": None,
            "parent_task_id": parent_task_id,
        }

    def update_task(
        self,
        task_id: str,
        status: Optional[str] = None,
        result: Optional[str] = None,
    ) -> Optional[dict]:
        if status and status not in _VALID_STATUSES:
            raise ValueError(f"Invalid status '{status}'. Must be one of {_VALID_STATUSES}")
        conn = self._conn()
        existing = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if existing is None:
            return None
        now = _utcnow()
        sets: List[str] = []
        params: List[Any] = []
        if status is not None:
            sets.append("status = ?")
            params.append(status)
        if result is not None:
            sets.append("result = ?")
            params.append(result)
        sets.append("updated_at = ?")
        params.append(now)
        params.append(task_id)
        with self._manager._lock:
            conn.execute(
                f"UPDATE tasks SET {', '.join(sets)} WHERE id = ?", params
            )
            conn.commit()
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return dict(row) if row else None

    def get_task(self, task_id: str) -> Optional[dict]:
        row = self._conn().execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return dict(row) if row else None

    def list_tasks(
        self,
        session_id: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[dict]:
        clauses: List[str] = []
        params: List[Any] = []
        if session_id is not None:
            clauses.append("session_id = ?")
            params.append(session_id)
        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = self._conn().execute(
            f"SELECT * FROM tasks{where} ORDER BY created_at DESC", params
        ).fetchall()
        return [dict(r) for r in rows]

    def get_task_tree(self, task_id: str) -> Optional[dict]:
        """Return a task with its full subtree of children (recursive)."""
        root = self.get_task(task_id)
        if root is None:
            return None
        self._populate_children(root)
        return root

    def _populate_children(self, task: dict) -> None:
        rows = self._conn().execute(
            "SELECT * FROM tasks WHERE parent_task_id = ? ORDER BY created_at",
            (task["id"],),
        ).fetchall()
        children = [dict(r) for r in rows]
        task["children"] = children
        for child in children:
            self._populate_children(child)


# ---------------------------------------------------------------------------
# Module-level singleton (lazy)
# ---------------------------------------------------------------------------

_manager: Optional[SessionManager] = None
_tracker: Optional[TaskTracker] = None
_init_lock = threading.RLock()  # 可重入锁：_get_tracker 持有本锁时会调用 _get_manager（同锁），必须用 RLock 避免同一线程重入死锁（曾致全服务瘫痪）


def _get_manager() -> SessionManager:
    global _manager
    if _manager is None:
        with _init_lock:
            if _manager is None:
                _manager = SessionManager()
    return _manager


def _get_tracker() -> TaskTracker:
    global _tracker
    if _tracker is None:
        with _init_lock:
            if _tracker is None:
                _tracker = TaskTracker(_get_manager())
    return _tracker


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------

def _tool_session_list(limit: int = 10, include_summary: bool = True) -> str:
    """List recent sessions."""
    mgr = _get_manager()
    sessions = mgr.list_sessions(limit=limit)
    if not sessions:
        return "No sessions found."
    lines: List[str] = []
    for s in sessions:
        line = f"- [{s['session_id'][:8]}] {s.get('title') or '(untitled)'}  (updated {s['updated_at']})"
        if include_summary and s.get("summary"):
            line += f"\n  Summary: {s['summary']}"
        lines.append(line)
    return "\n".join(lines)


def _tool_session_resume(session_id: str) -> str:
    """Resume a previous session, loading its context."""
    mgr = _get_manager()
    # Allow short prefix matching.
    if len(session_id) < 36:
        candidates = mgr.list_sessions(limit=1000)
        matches = [c for c in candidates if c["session_id"].startswith(session_id)]
        if len(matches) == 1:
            session_id = matches[0]["session_id"]
        elif len(matches) == 0:
            return f"Error: no session found matching '{session_id}'"
        else:
            ids = ", ".join(m["session_id"][:8] for m in matches[:5])
            return f"Error: ambiguous session prefix '{session_id}'. Matches: {ids}"

    state = mgr.get_session(session_id)
    if state is None:
        return f"Error: session '{session_id}' not found."
    ctx = state.get_full_context()
    msg_count = len(ctx["messages"])
    title = ctx.get("title") or "(untitled)"
    summary = ctx.get("context_summary") or ""
    parts = [
        f"Resumed session [{session_id[:8]}]: {title}",
        f"Messages loaded: {msg_count}",
    ]
    if summary:
        parts.append(f"Context summary: {summary[:500]}")
    # Show last few messages for orientation.
    recent = state.get_recent_messages(3)
    if recent:
        parts.append("Recent messages:")
        for m in recent:
            preview = m["content"][:120].replace("\n", " ")
            parts.append(f"  [{m['role']}] {preview}")
    return "\n".join(parts)


def _tool_session_search(query: str, limit: int = 10) -> str:
    """Search across all session history."""
    mgr = _get_manager()
    results = mgr.search_sessions(query, limit=limit)
    if not results:
        return f"No results found for '{query}'."
    lines = [f"Found {len(results)} result(s) for '{query}':"]
    for r in results:
        lines.append(f"- [{r['session_id'][:8]}] {r.get('title') or '(untitled)'}")
        if r.get("snippet"):
            lines.append(f"  ...{r['snippet']}...")
    return "\n".join(lines)


def _tool_task_create(description: str, parent_task_id: Optional[str] = None) -> str:
    """Create a tracked task in the current session."""
    tracker = _get_tracker()
    mgr = _get_manager()
    # Use the most recently updated session as "current".
    sessions = mgr.list_sessions(limit=1)
    if not sessions:
        state = mgr.create_session(title="Task session")
        session_id = state.session_id
    else:
        session_id = sessions[0]["session_id"]
    task = tracker.create_task(session_id, description, parent_task_id=parent_task_id)
    return (
        f"Task created: [{task['id'][:8]}] {description}\n"
        f"  Status: {task['status']}  |  Session: {session_id[:8]}"
    )


def _tool_task_update(task_id: str, status: Optional[str] = None, result: Optional[str] = None) -> str:
    """Update task status and/or result."""
    tracker = _get_tracker()
    # Allow short prefix matching.
    if len(task_id) < 36:
        all_tasks = tracker.list_tasks()
        matches = [t for t in all_tasks if t["id"].startswith(task_id)]
        if len(matches) == 1:
            task_id = matches[0]["id"]
        elif len(matches) == 0:
            return f"Error: no task found matching '{task_id}'"
        else:
            ids = ", ".join(m["id"][:8] for m in matches[:5])
            return f"Error: ambiguous task prefix '{task_id}'. Matches: {ids}"

    updated = tracker.update_task(task_id, status=status, result=result)
    if updated is None:
        return f"Error: task '{task_id}' not found."
    return (
        f"Task [{task_id[:8]}] updated:\n"
        f"  Status: {updated['status']}  |  Result: {updated.get('result') or '(none)'}"
    )


def _tool_task_list(status: Optional[str] = None, session_id: Optional[str] = None) -> str:
    """List tasks with optional status filter."""
    tracker = _get_tracker()
    tasks = tracker.list_tasks(session_id=session_id, status=status)
    if not tasks:
        filters = []
        if status:
            filters.append(f"status={status}")
        if session_id:
            filters.append(f"session={session_id[:8]}")
        fstr = f" ({', '.join(filters)})" if filters else ""
        return f"No tasks found{fstr}."
    lines = [f"Tasks ({len(tasks)}):"]
    for t in tasks:
        parent = f"  parent={t['parent_task_id'][:8]}" if t.get("parent_task_id") else ""
        result_snippet = ""
        if t.get("result"):
            r = t["result"][:80].replace("\n", " ")
            result_snippet = f"  result: {r}"
        lines.append(
            f"- [{t['id'][:8]}] [{t['status']}] {t['description']}{parent}{result_snippet}"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool registration (called by AST-based discovery)
# ---------------------------------------------------------------------------

def register(registry):
    """Register session & task tools with the tool registry."""

    registry.register(
        name="session_list",
        description=(
            "List recent conversation sessions. Returns session IDs, titles, "
            "timestamps, and optional summaries of the first user message."
        ),
        parameters={
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of sessions to return (default 10).",
                },
                "include_summary": {
                    "type": "boolean",
                    "description": "Include a short summary of each session (default true).",
                },
            },
        },
        handler=_tool_session_list,
        toolset="session",
        emoji="\U0001f4c2",  # 📂
    )

    registry.register(
        name="session_resume",
        description=(
            "Resume a previous session by ID (or short prefix). Loads the full "
            "conversation context so you can continue where you left off."
        ),
        parameters={
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "Full session ID or unique short prefix.",
                },
            },
            "required": ["session_id"],
        },
        handler=_tool_session_resume,
        toolset="session",
        emoji="\u23ea",  # ⏪
    )

    registry.register(
        name="session_search",
        description=(
            "Full-text search across all session message history. "
            "Returns matching sessions with relevant text snippets."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query — keywords or phrases to find in past conversations.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of results (default 10).",
                },
            },
            "required": ["query"],
        },
        handler=_tool_session_search,
        toolset="session",
        emoji="\U0001f50d",  # 🔍
    )

    registry.register(
        name="task_create",
        description=(
            "Create a tracked task in the current session. Tasks can be nested "
            "by specifying a parent_task_id for sub-task tracking."
        ),
        parameters={
            "type": "object",
            "properties": {
                "description": {
                    "type": "string",
                    "description": "What the task involves.",
                },
                "parent_task_id": {
                    "type": "string",
                    "description": "Optional parent task ID to create a sub-task.",
                },
            },
            "required": ["description"],
        },
        handler=_tool_task_create,
        toolset="session",
        emoji="\u2705",  # ✅
    )

    registry.register(
        name="task_update",
        description=(
            "Update a task's status and/or result. Valid statuses: "
            "pending, in_progress, completed, failed."
        ),
        parameters={
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "Full task ID or unique short prefix.",
                },
                "status": {
                    "type": "string",
                    "description": "New status: pending, in_progress, completed, or failed.",
                },
                "result": {
                    "type": "string",
                    "description": "Optional result description or outcome summary.",
                },
            },
            "required": ["task_id"],
        },
        handler=_tool_task_update,
        toolset="session",
        emoji="\u270f\ufe0f",  # ✏️
    )

    registry.register(
        name="task_list",
        description=(
            "List tracked tasks, optionally filtered by status and/or session."
        ),
        parameters={
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "description": "Filter by status: pending, in_progress, completed, or failed.",
                },
                "session_id": {
                    "type": "string",
                    "description": "Filter by session ID.",
                },
            },
        },
        handler=_tool_task_list,
        toolset="session",
        emoji="\U0001f4cb",  # 📋
    )
