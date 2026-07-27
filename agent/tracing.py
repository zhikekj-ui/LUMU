"""Observability & tracing — span-level tracking for agent execution.

Provides:
- TraceManager: SQLite-backed trace/span storage with hierarchical structure
- Span types: chat_turn, tool_call, llm_call, memory_op, error
- Per-span metrics: duration_ms, token_usage, cost_estimate
- Query API: get recent traces, slow spans, error patterns, cost summaries
- Performance baselines: rolling averages for latency, success rate, cost
- Auto-cleanup: configurable retention period

Design: minimal overhead, synchronous writes (SQLite is fast enough),
zero external dependencies.
"""
from core.logging_config import get_logger
_logger = get_logger("agent.tracing")
import json
import os
import sqlite3
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class Span:
    """A single unit of work within a trace."""
    span_id: str
    trace_id: str
    parent_span_id: Optional[str]
    name: str
    span_type: str  # chat_turn, tool_call, llm_call, memory_op, error, event
    started_at: float  # unix timestamp
    ended_at: Optional[float] = None
    duration_ms: Optional[float] = None
    status: str = "running"  # running, ok, error
    input_data: Optional[str] = None  # JSON
    output_data: Optional[str] = None  # JSON
    error_message: Optional[str] = None
    metadata: Optional[str] = None  # JSON: tags, model, toolset, etc.
    token_prompt: int = 0
    token_completion: int = 0
    cost_usd: float = 0.0

    def to_dict(self) -> dict:
        d = asdict(self)
        if self.metadata:
            try:
                d["metadata"] = json.loads(self.metadata)
            except (json.JSONDecodeError, TypeError):
                pass
        if self.input_data:
            try:
                d["input"] = json.loads(self.input_data)
            except (json.JSONDecodeError, TypeError):
                pass
        if self.output_data:
            try:
                d["output"] = json.loads(self.output_data)
            except (json.JSONDecodeError, TypeError):
                pass
        return d


# ---------------------------------------------------------------------------
# TraceManager
# ---------------------------------------------------------------------------

class TraceManager:
    """SQLite-backed trace storage with performance analytics."""

    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            base_dir = os.environ.get("AGENT_BASE_DIR", os.getcwd())
            db_path = os.path.join(base_dir, "data", "traces.db")
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db_path = db_path
        self._init_db()
        # In-memory active spans for fast lookup
        self._active_spans: dict[str, Span] = {}
        _logger.info("[tracing] TraceManager initialized")

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self):
        with self._get_conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS spans (
                    span_id         TEXT PRIMARY KEY,
                    trace_id        TEXT NOT NULL,
                    parent_span_id  TEXT,
                    name            TEXT NOT NULL,
                    span_type       TEXT NOT NULL,
                    started_at      REAL NOT NULL,
                    ended_at        REAL,
                    duration_ms     REAL,
                    status          TEXT DEFAULT 'running',
                    input_data      TEXT,
                    output_data     TEXT,
                    error_message   TEXT,
                    metadata        TEXT,
                    token_prompt    INTEGER DEFAULT 0,
                    token_completion INTEGER DEFAULT 0,
                    cost_usd        REAL DEFAULT 0.0
                );
                CREATE INDEX IF NOT EXISTS idx_spans_trace
                    ON spans(trace_id);
                CREATE INDEX IF NOT EXISTS idx_spans_type
                    ON spans(span_type);
                CREATE INDEX IF NOT EXISTS idx_spans_started
                    ON spans(started_at);
                CREATE INDEX IF NOT EXISTS idx_spans_status
                    ON spans(status);

                CREATE TABLE IF NOT EXISTS baselines (
                    metric      TEXT PRIMARY KEY,
                    value       REAL NOT NULL,
                    sample_count INTEGER DEFAULT 0,
                    updated_at  REAL NOT NULL
                );
            """)

    # --- Span lifecycle ---

    def start_span(
        self,
        name: str,
        span_type: str,
        trace_id: Optional[str] = None,
        parent_span_id: Optional[str] = None,
        metadata: Optional[dict] = None,
        input_data: Optional[Any] = None,
    ) -> Span:
        """Start a new span. Returns the Span object."""
        span = Span(
            span_id=str(uuid.uuid4())[:12],
            trace_id=trace_id or str(uuid.uuid4())[:12],
            parent_span_id=parent_span_id,
            name=name,
            span_type=span_type,
            started_at=time.time(),
            metadata=json.dumps(metadata) if metadata else None,
            input_data=json.dumps(input_data, ensure_ascii=False, default=str) if input_data else None,
        )
        self._active_spans[span.span_id] = span
        return span

    def end_span(
        self,
        span: Span,
        status: str = "ok",
        output_data: Optional[Any] = None,
        error_message: Optional[str] = None,
        token_prompt: int = 0,
        token_completion: int = 0,
        cost_usd: float = 0.0,
        metadata: Optional[dict] = None,
    ):
        """End a span and persist it."""
        span.ended_at = time.time()
        span.duration_ms = round((span.ended_at - span.started_at) * 1000, 1)
        span.status = status
        span.token_prompt = token_prompt
        span.token_completion = token_completion
        span.cost_usd = cost_usd
        if output_data is not None:
            span.output_data = json.dumps(output_data, ensure_ascii=False, default=str)
        if error_message:
            span.error_message = error_message
        if metadata:
            existing = json.loads(span.metadata) if span.metadata else {}
            existing.update(metadata)
            span.metadata = json.dumps(existing)

        self._persist_span(span)
        self._active_spans.pop(span.span_id, None)

        # Update baselines
        if status == "ok" and span.duration_ms is not None:
            self._update_baseline(span)

    def fail_span(self, span: Span, error: str, **kwargs):
        """Convenience: end a span with error status."""
        self.end_span(span, status="error", error_message=error, **kwargs)

    @contextmanager
    def trace(self, name: str, span_type: str = "operation", **kwargs):
        """Context manager for automatic span tracking."""
        span = self.start_span(name, span_type, **kwargs)
        try:
            yield span
            self.end_span(span)
        except Exception as e:
            self.fail_span(span, str(e))
            raise

    # --- Persistence ---

    def _persist_span(self, span: Span):
        with self._get_conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO spans
                   (span_id, trace_id, parent_span_id, name, span_type,
                    started_at, ended_at, duration_ms, status,
                    input_data, output_data, error_message, metadata,
                    token_prompt, token_completion, cost_usd)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    span.span_id, span.trace_id, span.parent_span_id,
                    span.name, span.span_type, span.started_at,
                    span.ended_at, span.duration_ms, span.status,
                    span.input_data, span.output_data, span.error_message,
                    span.metadata, span.token_prompt, span.token_completion,
                    span.cost_usd,
                ),
            )

    # --- Query API ---

    def get_trace(self, trace_id: str) -> list[dict]:
        """Get all spans for a trace, ordered by start time."""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM spans WHERE trace_id = ? ORDER BY started_at",
                (trace_id,),
            ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def get_recent_traces(self, limit: int = 20) -> list[dict]:
        """Get recent trace summaries (one row per trace)."""
        with self._get_conn() as conn:
            rows = conn.execute(
                """SELECT trace_id,
                          MIN(name) as root_name,
                          MIN(started_at) as started_at,
                          MAX(ended_at) - MIN(started_at) as total_duration_s,
                          COUNT(*) as span_count,
                          SUM(CASE WHEN status='error' THEN 1 ELSE 0 END) as error_count,
                          SUM(token_prompt) as total_prompt_tokens,
                          SUM(token_completion) as total_completion_tokens,
                          ROUND(SUM(cost_usd), 6) as total_cost_usd
                   FROM spans
                   GROUP BY trace_id
                   ORDER BY started_at DESC
                   LIMIT ?""",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_slow_spans(self, threshold_ms: float = 5000, limit: int = 20) -> list[dict]:
        """Get the slowest spans above a threshold."""
        with self._get_conn() as conn:
            rows = conn.execute(
                """SELECT * FROM spans
                   WHERE duration_ms > ? AND status = 'ok'
                   ORDER BY duration_ms DESC LIMIT ?""",
                (threshold_ms, limit),
            ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def get_error_summary(self, hours: int = 24, limit: int = 20) -> list[dict]:
        """Get recent errors grouped by message."""
        cutoff = time.time() - (hours * 3600)
        with self._get_conn() as conn:
            rows = conn.execute(
                """SELECT error_message, name, span_type,
                          COUNT(*) as count,
                          MAX(started_at) as last_seen
                   FROM spans
                   WHERE status = 'error' AND started_at > ?
                   GROUP BY error_message, name
                   ORDER BY count DESC LIMIT ?""",
                (cutoff, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_cost_summary(self, hours: int = 24) -> dict:
        """Get cost and token usage summary for a time period."""
        cutoff = time.time() - (hours * 3600)
        with self._get_conn() as conn:
            row = conn.execute(
                """SELECT
                       COUNT(*) as total_spans,
                       SUM(CASE WHEN span_type='llm_call' THEN 1 ELSE 0 END) as llm_calls,
                       SUM(token_prompt) as total_prompt_tokens,
                       SUM(token_completion) as total_completion_tokens,
                       ROUND(SUM(cost_usd), 6) as total_cost_usd,
                       ROUND(AVG(duration_ms), 1) as avg_duration_ms
                   FROM spans
                   WHERE started_at > ?""",
                (cutoff,),
            ).fetchone()
        return dict(row) if row else {}

    def get_tool_stats(self, hours: int = 24) -> list[dict]:
        """Get per-tool usage statistics."""
        cutoff = time.time() - (hours * 3600)
        with self._get_conn() as conn:
            rows = conn.execute(
                """SELECT name as tool_name,
                          COUNT(*) as calls,
                          SUM(CASE WHEN status='error' THEN 1 ELSE 0 END) as errors,
                          ROUND(AVG(duration_ms), 1) as avg_ms,
                          ROUND(MAX(duration_ms), 1) as max_ms
                   FROM spans
                   WHERE span_type = 'tool_call' AND started_at > ?
                   GROUP BY name
                   ORDER BY calls DESC""",
                (cutoff,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_baselines(self) -> dict:
        """Get current performance baselines."""
        with self._get_conn() as conn:
            rows = conn.execute("SELECT * FROM baselines").fetchall()
        return {r["metric"]: {"value": r["value"], "samples": r["sample_count"]} for r in rows}

    # --- Baseline tracking ---

    def _update_baseline(self, span: Span):
        """Update rolling averages for key metrics."""
        metrics = {}
        if span.duration_ms is not None:
            metrics[f"latency_{span.span_type}"] = span.duration_ms
        if span.token_prompt or span.token_completion:
            metrics["tokens_per_call"] = span.token_prompt + span.token_completion
        if span.cost_usd > 0:
            metrics["cost_per_call"] = span.cost_usd

        with self._get_conn() as conn:
            for metric, value in metrics.items():
                row = conn.execute(
                    "SELECT value, sample_count FROM baselines WHERE metric = ?",
                    (metric,),
                ).fetchone()
                if row:
                    old_val, n = row["value"], row["sample_count"]
                    # Exponential moving average (alpha = 0.1 for stability)
                    alpha = min(0.1, 1.0 / (n + 1))
                    new_val = old_val * (1 - alpha) + value * alpha
                    conn.execute(
                        """UPDATE baselines SET value=?, sample_count=sample_count+1,
                           updated_at=? WHERE metric=?""",
                        (new_val, time.time(), metric),
                    )
                else:
                    conn.execute(
                        "INSERT INTO baselines (metric, value, sample_count, updated_at) VALUES (?,?,1,?)",
                        (metric, value, time.time()),
                    )

    # --- Cleanup ---

    def cleanup(self, retention_days: int = 7):
        """Remove old spans beyond retention period."""
        cutoff = time.time() - (retention_days * 86400)
        with self._get_conn() as conn:
            result = conn.execute(
                "DELETE FROM spans WHERE started_at < ?", (cutoff,)
            )
            if result.rowcount > 0:
                _logger.info(f"[tracing] Cleaned up {result.rowcount} old spans")

    # --- Helpers ---

    @staticmethod
    def _row_to_dict(row) -> dict:
        d = dict(row)
        for key in ("input_data", "output_data", "metadata"):
            if d.get(key):
                try:
                    d[key] = json.loads(d[key])
                except (json.JSONDecodeError, TypeError):
                    pass
        return d


# ---------------------------------------------------------------------------
# Global instance (lazy init)
# ---------------------------------------------------------------------------

_tracer: Optional[TraceManager] = None


def get_tracer() -> TraceManager:
    global _tracer
    if _tracer is None:
        _tracer = TraceManager()
    return _tracer
