"""Adaptive learning automation — automatic failure analysis and dynamic tool selection.

Provides:
- AutoLearner: automatic "failure → analysis → strategy adjustment → retry" loop
- DynamicToolSelector: prefer tools based on historical success rates
- StrategyAdjuster: adjust prompts/parameters based on feedback patterns
- PerformanceTracker: track per-tool success rates, latency, cost
- AutoRetry: intelligent retry with backoff and alternative strategies

Builds on top of the existing LearningEngine but adds automation:
- No manual trigger needed — analyzes failures automatically
- Tracks tool-level metrics (success rate, avg latency)
- Adjusts tool selection weights based on performance
- Records strategy adjustments for future reference
"""
from core.logging_config import get_logger
_logger = get_logger("agent.adaptive")
import json
import os
import sqlite3
import time
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Optional


@dataclass
class ToolMetrics:
    """Performance metrics for a single tool."""
    tool_name: str
    total_calls: int = 0
    success_count: int = 0
    failure_count: int = 0
    avg_latency_ms: float = 0.0
    max_latency_ms: float = 0.0
    avg_cost_usd: float = 0.0
    success_rate: float = 1.0
    last_used: float = 0.0
    recent_failures: list = field(default_factory=list)  # Last 5 failures

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class StrategyAdjustment:
    """A recorded strategy adjustment."""
    adjustment_id: str
    timestamp: float
    trigger: str  # What triggered the adjustment
    tool_name: Optional[str]
    old_strategy: str
    new_strategy: str
    reason: str
    outcome: Optional[str] = None  # "improved", "no_change", "worse"

    def to_dict(self) -> dict:
        return asdict(self)


class AutoLearner:
    """Automatic learning and strategy adjustment engine."""

    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            base_dir = os.environ.get("AGENT_BASE_DIR", os.getcwd())
            db_path = os.path.join(base_dir, "data", "adaptive_learning.db")
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db_path = db_path
        self._init_db()
        # In-memory metrics cache
        self._tool_metrics: dict[str, ToolMetrics] = {}
        self._load_metrics()
        _logger.info("[adaptive] AutoLearner initialized")

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self):
        with self._get_conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS tool_metrics (
                    tool_name       TEXT PRIMARY KEY,
                    total_calls     INTEGER DEFAULT 0,
                    success_count   INTEGER DEFAULT 0,
                    failure_count   INTEGER DEFAULT 0,
                    avg_latency_ms  REAL DEFAULT 0.0,
                    max_latency_ms  REAL DEFAULT 0.0,
                    avg_cost_usd    REAL DEFAULT 0.0,
                    success_rate    REAL DEFAULT 1.0,
                    last_used       REAL DEFAULT 0.0,
                    recent_failures TEXT DEFAULT '[]'
                );

                CREATE TABLE IF NOT EXISTS strategy_adjustments (
                    adjustment_id   TEXT PRIMARY KEY,
                    timestamp       REAL NOT NULL,
                    trigger         TEXT NOT NULL,
                    tool_name       TEXT,
                    old_strategy    TEXT NOT NULL,
                    new_strategy    TEXT NOT NULL,
                    reason          TEXT NOT NULL,
                    outcome         TEXT
                );

                CREATE TABLE IF NOT EXISTS failure_patterns (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    tool_name       TEXT NOT NULL,
                    error_pattern   TEXT NOT NULL,
                    occurrence_count INTEGER DEFAULT 1,
                    first_seen      REAL NOT NULL,
                    last_seen       REAL NOT NULL,
                    suggested_fix   TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_failures_tool
                    ON failure_patterns(tool_name);
            """)

    # --- Tool metrics tracking ---

    def record_tool_call(
        self,
        tool_name: str,
        success: bool,
        latency_ms: float = 0.0,
        cost_usd: float = 0.0,
        error_message: Optional[str] = None,
    ):
        """Record a tool call result and update metrics."""
        if tool_name not in self._tool_metrics:
            self._tool_metrics[tool_name] = ToolMetrics(tool_name=tool_name)

        metrics = self._tool_metrics[tool_name]
        metrics.total_calls += 1
        metrics.last_used = time.time()

        if success:
            metrics.success_count += 1
        else:
            metrics.failure_count += 1
            # Track recent failures (keep last 5)
            metrics.recent_failures.append({
                "error": error_message,
                "timestamp": time.time(),
            })
            if len(metrics.recent_failures) > 5:
                metrics.recent_failures = metrics.recent_failures[-5:]

        # Update latency (exponential moving average)
        if latency_ms > 0:
            if metrics.avg_latency_ms == 0:
                metrics.avg_latency_ms = latency_ms
            else:
                metrics.avg_latency_ms = metrics.avg_latency_ms * 0.9 + latency_ms * 0.1
            metrics.max_latency_ms = max(metrics.max_latency_ms, latency_ms)

        # Update cost
        if cost_usd > 0:
            if metrics.avg_cost_usd == 0:
                metrics.avg_cost_usd = cost_usd
            else:
                total_cost = metrics.avg_cost_usd * (metrics.total_calls - 1) + cost_usd
                metrics.avg_cost_usd = total_cost / metrics.total_calls

        # Update success rate
        metrics.success_rate = metrics.success_count / metrics.total_calls if metrics.total_calls > 0 else 1.0

        # Persist
        self._persist_metrics(metrics)

        # Auto-analyze failures
        if not success and error_message:
            self._analyze_failure(tool_name, error_message)

    def get_tool_metrics(self, tool_name: str) -> Optional[dict]:
        """Get metrics for a specific tool."""
        metrics = self._tool_metrics.get(tool_name)
        return metrics.to_dict() if metrics else None

    def get_all_metrics(self) -> list[dict]:
        """Get metrics for all tools."""
        return [m.to_dict() for m in self._tool_metrics.values()]

    def get_top_tools(self, limit: int = 10, min_calls: int = 5) -> list[dict]:
        """Get top-performing tools by success rate."""
        tools = [
            m.to_dict() for m in self._tool_metrics.values()
            if m.total_calls >= min_calls
        ]
        return sorted(tools, key=lambda x: x["success_rate"], reverse=True)[:limit]

    def get_worst_tools(self, limit: int = 10, min_calls: int = 5) -> list[dict]:
        """Get worst-performing tools by success rate."""
        tools = [
            m.to_dict() for m in self._tool_metrics.values()
            if m.total_calls >= min_calls
        ]
        return sorted(tools, key=lambda x: x["success_rate"])[:limit]

    # --- Dynamic tool selection ---

    def select_tool(
        self,
        candidate_tools: list[str],
        context: Optional[str] = None,
    ) -> str:
        """Select the best tool from candidates based on historical performance.

        Uses success rate as primary factor, with latency as tiebreaker.
        """
        if not candidate_tools:
            return ""

        # Score each tool
        scored = []
        for tool_name in candidate_tools:
            metrics = self._tool_metrics.get(tool_name)
            if not metrics or metrics.total_calls < 3:
                # No data — give benefit of the doubt
                scored.append((tool_name, 0.8, 0))
            else:
                # Score = success_rate * (1 - normalized_latency)
                # Normalize latency to 0-1 range (cap at 10s)
                norm_latency = min(metrics.avg_latency_ms / 10000, 1.0)
                score = metrics.success_rate * (1 - norm_latency * 0.3)
                scored.append((tool_name, score, metrics.success_rate))

        # Sort by score descending
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[0][0] if scored else candidate_tools[0]

    def get_tool_weights(self) -> dict[str, float]:
        """Get tool selection weights based on performance."""
        weights = {}
        for tool_name, metrics in self._tool_metrics.items():
            if metrics.total_calls >= 3:
                weights[tool_name] = metrics.success_rate
            else:
                weights[tool_name] = 0.8  # Default weight for unknown tools
        return weights

    # --- Automatic failure analysis ---

    def _analyze_failure(self, tool_name: str, error_message: str):
        """Analyze a failure and look for patterns."""
        # Extract error pattern (simplified — remove specific values)
        pattern = self._extract_error_pattern(error_message)

        with self._get_conn() as conn:
            # Check if pattern already exists
            existing = conn.execute(
                "SELECT * FROM failure_patterns WHERE tool_name = ? AND error_pattern = ?",
                (tool_name, pattern),
            ).fetchone()

            if existing:
                # Update occurrence count
                conn.execute(
                    """UPDATE failure_patterns
                       SET occurrence_count = occurrence_count + 1, last_seen = ?
                       WHERE id = ?""",
                    (time.time(), existing["id"]),
                )
            else:
                # New pattern
                conn.execute(
                    """INSERT INTO failure_patterns
                       (tool_name, error_pattern, first_seen, last_seen)
                       VALUES (?,?,?,?)""",
                    (tool_name, pattern, time.time(), time.time()),
                )

        # Check if this tool has recurring failures
        self._check_recurring_failures(tool_name)

    def _extract_error_pattern(self, error_message: str) -> str:
        """Extract a generalized error pattern from a specific error message."""
        # Remove numbers, UUIDs, specific paths
        import re
        pattern = re.sub(r'\b\d+\b', 'N', error_message)
        pattern = re.sub(r'[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}', 'UUID', pattern)
        pattern = re.sub(r'/[^\s]+', 'PATH', pattern)
        # Truncate
        return pattern[:200]

    def _check_recurring_failures(self, tool_name: str, threshold: int = 3):
        """Check if a tool has recurring failures and suggest adjustments."""
        with self._get_conn() as conn:
            patterns = conn.execute(
                """SELECT error_pattern, occurrence_count, suggested_fix
                   FROM failure_patterns
                   WHERE tool_name = ? AND occurrence_count >= ?
                   ORDER BY occurrence_count DESC""",
                (tool_name, threshold),
            ).fetchall()

        if patterns:
            # Generate strategy adjustment
            for p in patterns:
                self._suggest_adjustment(
                    tool_name=tool_name,
                    trigger=f"recurring_failure:{p['error_pattern'][:50]}",
                    reason=f"Tool {tool_name} failed {p['occurrence_count']} times with pattern: {p['error_pattern'][:100]}",
                )

    def _suggest_adjustment(
        self,
        tool_name: str,
        trigger: str,
        reason: str,
    ):
        """Suggest a strategy adjustment."""
        import uuid
        adjustment = StrategyAdjustment(
            adjustment_id=str(uuid.uuid4())[:12],
            timestamp=time.time(),
            trigger=trigger,
            tool_name=tool_name,
            old_strategy="default",
            new_strategy="avoid_or_retry",
            reason=reason,
        )
        with self._get_conn() as conn:
            conn.execute(
                """INSERT INTO strategy_adjustments
                   (adjustment_id, timestamp, trigger, tool_name, old_strategy, new_strategy, reason)
                   VALUES (?,?,?,?,?,?,?)""",
                (
                    adjustment.adjustment_id, adjustment.timestamp,
                    adjustment.trigger, adjustment.tool_name,
                    adjustment.old_strategy, adjustment.new_strategy,
                    adjustment.reason,
                ),
            )

    # --- Auto-retry logic ---

    def should_retry(
        self,
        tool_name: str,
        attempt: int,
        max_attempts: int = 3,
    ) -> tuple[bool, float]:
        """Decide if a failed tool call should be retried.

        Returns: (should_retry, delay_seconds)
        """
        if attempt >= max_attempts:
            return False, 0

        metrics = self._tool_metrics.get(tool_name)
        if not metrics:
            # No data — retry with short delay
            return True, 1.0

        # If success rate is very low, don't bother retrying
        if metrics.total_calls >= 10 and metrics.success_rate < 0.2:
            return False, 0

        # Exponential backoff based on attempt number
        delay = min(2 ** attempt, 10.0)
        return True, delay

    def get_adjustments(self, limit: int = 20) -> list[dict]:
        """Get recent strategy adjustments."""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM strategy_adjustments ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_failure_patterns(self, tool_name: Optional[str] = None) -> list[dict]:
        """Get recurring failure patterns."""
        with self._get_conn() as conn:
            if tool_name:
                rows = conn.execute(
                    "SELECT * FROM failure_patterns WHERE tool_name = ? ORDER BY occurrence_count DESC",
                    (tool_name,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM failure_patterns ORDER BY occurrence_count DESC LIMIT 50"
                ).fetchall()
        return [dict(r) for r in rows]

    # --- Persistence ---

    def _load_metrics(self):
        """Load metrics from DB into memory."""
        with self._get_conn() as conn:
            rows = conn.execute("SELECT * FROM tool_metrics").fetchall()
        for r in rows:
            d = dict(r)
            d["recent_failures"] = json.loads(d["recent_failures"])
            self._tool_metrics[d["tool_name"]] = ToolMetrics(**d)

    def _persist_metrics(self, metrics: ToolMetrics):
        """Persist metrics to DB."""
        with self._get_conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO tool_metrics
                   (tool_name, total_calls, success_count, failure_count,
                    avg_latency_ms, max_latency_ms, avg_cost_usd, success_rate,
                    last_used, recent_failures)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    metrics.tool_name, metrics.total_calls, metrics.success_count,
                    metrics.failure_count, metrics.avg_latency_ms, metrics.max_latency_ms,
                    metrics.avg_cost_usd, metrics.success_rate, metrics.last_used,
                    json.dumps(metrics.recent_failures),
                ),
            )


# ---------------------------------------------------------------------------
# Global instance
# ---------------------------------------------------------------------------

_auto_learner: Optional[AutoLearner] = None


def get_auto_learner() -> AutoLearner:
    global _auto_learner
    if _auto_learner is None:
        _auto_learner = AutoLearner()
    return _auto_learner
