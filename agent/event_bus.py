"""Event-driven architecture — internal event bus with webhook triggers.

Provides:
- EventBus: publish/subscribe event system for internal agent communication
- Event types: tool_executed, error_occurred, memory_updated, session_started,
  cron_fired, webhook_received, user_feedback, agent_completed
- WebhookTrigger: map incoming webhooks to agent actions
- Event handlers: automatic reactions to specific event patterns
- Event history: SQLite-backed event log with query API

Design: in-memory pub/sub with SQLite persistence for audit trail.
Webhook endpoint already exists in API — this adds event routing on top.
"""
from core.logging_config import get_logger
_logger = get_logger("agent.event_bus")
import asyncio
import json
import os
import sqlite3
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Callable, Optional
from enum import Enum


class EventType(str, Enum):
    # Agent lifecycle
    AGENT_STARTED = "agent.started"
    AGENT_STOPPED = "agent.stopped"
    SESSION_STARTED = "session.started"
    SESSION_ENDED = "session.ended"

    # Tool execution
    TOOL_EXECUTED = "tool.executed"
    TOOL_FAILED = "tool.failed"

    # LLM
    LLM_CALL = "llm.call"
    LLM_ERROR = "llm.error"

    # Memory
    MEMORY_SAVED = "memory.saved"
    MEMORY_SEARCHED = "memory.searched"

    # Tasks
    TASK_CREATED = "task.created"
    TASK_COMPLETED = "task.completed"
    TASK_FAILED = "task.failed"

    # Cron
    CRON_FIRED = "cron.fired"
    CRON_COMPLETED = "cron.completed"

    # Webhook
    WEBHOOK_RECEIVED = "webhook.received"

    # Human interaction
    USER_FEEDBACK = "user.feedback"
    APPROVAL_REQUESTED = "approval.requested"
    APPROVAL_GRANTED = "approval.granted"
    APPROVAL_DENIED = "approval.denied"

    # System
    ERROR = "system.error"
    WARNING = "system.warning"


@dataclass
class Event:
    """A single event in the system."""
    event_id: str
    event_type: str
    source: str  # component that emitted the event
    timestamp: float
    data: Optional[dict] = None
    session_id: Optional[str] = None
    trace_id: Optional[str] = None
    metadata: Optional[dict] = None

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Event handler type
# ---------------------------------------------------------------------------

EventHandler = Callable[[Event], Any]
AsyncEventHandler = Callable[[Event], Any]


# ---------------------------------------------------------------------------
# EventBus
# ---------------------------------------------------------------------------

class EventBus:
    """In-memory pub/sub event bus with SQLite persistence."""

    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            base_dir = os.environ.get("AGENT_BASE_DIR", os.getcwd())
            db_path = os.path.join(base_dir, "data", "events.db")
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db_path = db_path
        self._handlers: dict[str, list[EventHandler]] = defaultdict(list)
        self._async_handlers: dict[str, list[AsyncEventHandler]] = defaultdict(list)
        self._init_db()
        _logger.info("[events] EventBus initialized")

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self):
        with self._get_conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS events (
                    event_id    TEXT PRIMARY KEY,
                    event_type  TEXT NOT NULL,
                    source      TEXT NOT NULL,
                    timestamp   REAL NOT NULL,
                    data        TEXT,
                    session_id  TEXT,
                    trace_id    TEXT,
                    metadata    TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_events_type
                    ON events(event_type);
                CREATE INDEX IF NOT EXISTS idx_events_time
                    ON events(timestamp);
                CREATE INDEX IF NOT EXISTS idx_events_session
                    ON events(session_id);

                CREATE TABLE IF NOT EXISTS webhook_triggers (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    pattern     TEXT NOT NULL,  -- URL path or event pattern
                    action      TEXT NOT NULL,  -- "run_agent", "emit_event"
                    config      TEXT NOT NULL,  -- JSON: message, event_type, etc.
                    enabled     INTEGER DEFAULT 1,
                    created_at  REAL NOT NULL
                );
            """)

    # --- Publish ---

    def emit(
        self,
        event_type: str,
        source: str,
        data: Optional[dict] = None,
        session_id: Optional[str] = None,
        trace_id: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> Event:
        """Emit an event. Calls all registered handlers synchronously."""
        event = Event(
            event_id=str(uuid.uuid4())[:12],
            event_type=event_type,
            source=source,
            timestamp=time.time(),
            data=data,
            session_id=session_id,
            trace_id=trace_id,
            metadata=metadata,
        )
        # Persist
        self._persist_event(event)
        # Call sync handlers
        for handler in self._handlers.get(event_type, []):
            try:
                handler(event)
            except Exception as e:
                _logger.info(f"[events] Handler error for {event_type}: {e}")
        # Call wildcard handlers
        for handler in self._handlers.get("*", []):
            try:
                handler(event)
            except Exception as e:
                _logger.info(f"[events] Wildcard handler error: {e}")
        return event

    async def emit_async(
        self,
        event_type: str,
        source: str,
        data: Optional[dict] = None,
        session_id: Optional[str] = None,
        trace_id: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> Event:
        """Emit an event and call async handlers."""
        event = self.emit(event_type, source, data, session_id, trace_id, metadata)
        # Call async handlers
        for handler in self._async_handlers.get(event_type, []):
            try:
                await handler(event)
            except Exception as e:
                _logger.info(f"[events] Async handler error for {event_type}: {e}")
        for handler in self._async_handlers.get("*", []):
            try:
                await handler(event)
            except Exception as e:
                _logger.info(f"[events] Async wildcard handler error: {e}")
        return event

    # --- Subscribe ---

    def on(self, event_type: str, handler: EventHandler):
        """Register a synchronous event handler."""
        self._handlers[event_type].append(handler)

    def on_async(self, event_type: str, handler: AsyncEventHandler):
        """Register an asynchronous event handler."""
        self._async_handlers[event_type].append(handler)

    def off(self, event_type: str, handler: EventHandler):
        """Remove an event handler."""
        if handler in self._handlers.get(event_type, []):
            self._handlers[event_type].remove(handler)

    # --- Webhook triggers ---

    def register_webhook_trigger(
        self,
        pattern: str,
        action: str,
        config: dict,
    ) -> int:
        """Register a webhook trigger.

        Args:
            pattern: URL path pattern (e.g., "/hooks/email-received")
            action: What to do ("run_agent", "emit_event")
            config: Configuration (e.g., {"message": "Process this email"})
        """
        with self._get_conn() as conn:
            cursor = conn.execute(
                """INSERT INTO webhook_triggers (pattern, action, config, created_at)
                   VALUES (?,?,?,?)""",
                (pattern, action, json.dumps(config, ensure_ascii=False), time.time()),
            )
            return cursor.lastrowid

    def get_webhook_trigger(self, pattern: str) -> Optional[dict]:
        """Get webhook trigger config for a pattern."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM webhook_triggers WHERE pattern = ? AND enabled = 1",
                (pattern,),
            ).fetchone()
        if row:
            d = dict(row)
            d["config"] = json.loads(d["config"])
            return d
        return None

    def list_webhook_triggers(self) -> list[dict]:
        """List all webhook triggers."""
        with self._get_conn() as conn:
            rows = conn.execute("SELECT * FROM webhook_triggers ORDER BY created_at DESC").fetchall()
        results = []
        for r in rows:
            d = dict(r)
            d["config"] = json.loads(d["config"])
            results.append(d)
        return results

    def delete_webhook_trigger(self, trigger_id: int) -> bool:
        """Delete a webhook trigger."""
        with self._get_conn() as conn:
            result = conn.execute("DELETE FROM webhook_triggers WHERE id = ?", (trigger_id,))
            return result.rowcount > 0

    # --- Query API ---

    def get_recent_events(
        self,
        event_type: Optional[str] = None,
        session_id: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict]:
        """Get recent events with optional filters."""
        query = "SELECT * FROM events WHERE 1=1"
        params = []
        if event_type:
            query += " AND event_type = ?"
            params.append(event_type)
        if session_id:
            query += " AND session_id = ?"
            params.append(session_id)
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        with self._get_conn() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def get_event_summary(self, hours: int = 24) -> dict:
        """Get event counts by type for a time period."""
        cutoff = time.time() - (hours * 3600)
        with self._get_conn() as conn:
            rows = conn.execute(
                """SELECT event_type, COUNT(*) as count
                   FROM events WHERE timestamp > ?
                   GROUP BY event_type
                   ORDER BY count DESC""",
                (cutoff,),
            ).fetchall()
        return {r["event_type"]: r["count"] for r in rows}

    # --- Cleanup ---

    def cleanup(self, retention_days: int = 7):
        """Remove old events."""
        cutoff = time.time() - (retention_days * 86400)
        with self._get_conn() as conn:
            result = conn.execute("DELETE FROM events WHERE timestamp < ?", (cutoff,))
            if result.rowcount > 0:
                _logger.info(f"[events] Cleaned up {result.rowcount} old events")

    # --- Persistence ---

    def _persist_event(self, event: Event):
        with self._get_conn() as conn:
            conn.execute(
                """INSERT INTO events
                   (event_id, event_type, source, timestamp, data, session_id, trace_id, metadata)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (
                    event.event_id, event.event_type, event.source,
                    event.timestamp,
                    json.dumps(event.data, ensure_ascii=False, default=str) if event.data else None,
                    event.session_id, event.trace_id,
                    json.dumps(event.metadata) if event.metadata else None,
                ),
            )

    @staticmethod
    def _row_to_dict(row) -> dict:
        d = dict(row)
        for key in ("data", "metadata"):
            if d.get(key):
                try:
                    d[key] = json.loads(d[key])
                except (json.JSONDecodeError, TypeError):
                    pass
        return d


# ---------------------------------------------------------------------------
# Global instance
# ---------------------------------------------------------------------------

_event_bus: Optional[EventBus] = None


def get_event_bus() -> EventBus:
    global _event_bus
    if _event_bus is None:
        _event_bus = EventBus()
    return _event_bus
