"""Checkpoint & state persistence — save and restore agent execution state.

Provides:
- CheckpointManager: save/restore agent state at arbitrary points
- State serialization: messages, tool results, intermediate data
- Recovery: resume from last checkpoint after crash/restart
- Workflow state: track multi-step task progress with named stages
- TTL: automatic cleanup of old checkpoints

Design: checkpoints stored in SQLite with JSON-serialized state.
Each checkpoint captures a snapshot of the agent's execution context.
"""
from core.logging_config import get_logger
_logger = get_logger("agent.checkpoint")
import json
import os
import sqlite3
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Optional


@dataclass
class Checkpoint:
    """A saved snapshot of agent state."""
    checkpoint_id: str
    session_id: str
    trace_id: Optional[str]
    stage: str  # named stage (e.g., "downloading_files", "processing_data")
    state: dict  # serialized agent state
    created_at: float
    metadata: Optional[dict] = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class WorkflowState:
    """Track a multi-step workflow's progress."""
    workflow_id: str
    session_id: str
    name: str
    stages: list[dict]  # [{name, status, started_at, completed_at, data}]
    current_stage: Optional[str]
    status: str  # running, paused, completed, failed
    created_at: float
    updated_at: float
    result: Optional[dict] = None

    def to_dict(self) -> dict:
        return asdict(self)


class CheckpointManager:
    """Manage agent execution checkpoints and workflow state."""

    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            base_dir = os.environ.get("AGENT_BASE_DIR", os.getcwd())
            db_path = os.path.join(base_dir, "data", "checkpoints.db")
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db_path = db_path
        self._init_db()
        _logger.info("[checkpoint] CheckpointManager initialized")

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self):
        with self._get_conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS checkpoints (
                    checkpoint_id TEXT PRIMARY KEY,
                    session_id    TEXT NOT NULL,
                    trace_id      TEXT,
                    stage         TEXT NOT NULL,
                    state         TEXT NOT NULL,
                    created_at    REAL NOT NULL,
                    metadata      TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_ckpt_session
                    ON checkpoints(session_id);
                CREATE INDEX IF NOT EXISTS idx_ckpt_created
                    ON checkpoints(created_at);

                CREATE TABLE IF NOT EXISTS workflows (
                    workflow_id   TEXT PRIMARY KEY,
                    session_id    TEXT NOT NULL,
                    name          TEXT NOT NULL,
                    stages        TEXT NOT NULL,
                    current_stage TEXT,
                    status        TEXT DEFAULT 'running',
                    created_at    REAL NOT NULL,
                    updated_at    REAL NOT NULL,
                    result        TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_wf_session
                    ON workflows(session_id);
                CREATE INDEX IF NOT EXISTS idx_wf_status
                    ON workflows(status);
            """)

    # --- Checkpoint API ---

    def save_checkpoint(
        self,
        session_id: str,
        stage: str,
        state: dict,
        trace_id: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> Checkpoint:
        """Save a checkpoint of the current agent state."""
        cp = Checkpoint(
            checkpoint_id=str(uuid.uuid4())[:12],
            session_id=session_id,
            trace_id=trace_id,
            stage=stage,
            state=state,
            created_at=time.time(),
            metadata=metadata,
        )
        with self._get_conn() as conn:
            conn.execute(
                """INSERT INTO checkpoints
                   (checkpoint_id, session_id, trace_id, stage, state, created_at, metadata)
                   VALUES (?,?,?,?,?,?,?)""",
                (
                    cp.checkpoint_id, cp.session_id, cp.trace_id,
                    cp.stage, json.dumps(state, ensure_ascii=False, default=str),
                    cp.created_at,
                    json.dumps(metadata) if metadata else None,
                ),
            )
        return cp

    def load_checkpoint(self, checkpoint_id: str) -> Optional[Checkpoint]:
        """Load a specific checkpoint."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM checkpoints WHERE checkpoint_id = ?",
                (checkpoint_id,),
            ).fetchone()
        if row:
            return self._row_to_checkpoint(row)
        return None

    def get_latest_checkpoint(self, session_id: str) -> Optional[Checkpoint]:
        """Get the most recent checkpoint for a session."""
        with self._get_conn() as conn:
            row = conn.execute(
                """SELECT * FROM checkpoints
                   WHERE session_id = ?
                   ORDER BY created_at DESC LIMIT 1""",
                (session_id,),
            ).fetchone()
        if row:
            return self._row_to_checkpoint(row)
        return None

    def list_checkpoints(self, session_id: str, limit: int = 10) -> list[dict]:
        """List checkpoints for a session."""
        with self._get_conn() as conn:
            rows = conn.execute(
                """SELECT checkpoint_id, stage, created_at, metadata
                   FROM checkpoints WHERE session_id = ?
                   ORDER BY created_at DESC LIMIT ?""",
                (session_id, limit),
            ).fetchall()
        results = []
        for r in rows:
            d = dict(r)
            if d.get("metadata"):
                try:
                    d["metadata"] = json.loads(d["metadata"])
                except (json.JSONDecodeError, TypeError):
                    pass
            results.append(d)
        return results

    def delete_checkpoint(self, checkpoint_id: str) -> bool:
        """Delete a checkpoint."""
        with self._get_conn() as conn:
            result = conn.execute(
                "DELETE FROM checkpoints WHERE checkpoint_id = ?",
                (checkpoint_id,),
            )
            return result.rowcount > 0

    # --- Workflow API ---

    def create_workflow(
        self,
        session_id: str,
        name: str,
        stages: list[str],
    ) -> WorkflowState:
        """Create a new workflow with named stages."""
        wf = WorkflowState(
            workflow_id=str(uuid.uuid4())[:12],
            session_id=session_id,
            name=name,
            stages=[{"name": s, "status": "pending", "started_at": None, "completed_at": None, "data": None} for s in stages],
            current_stage=stages[0] if stages else None,
            status="running",
            created_at=time.time(),
            updated_at=time.time(),
        )
        with self._get_conn() as conn:
            conn.execute(
                """INSERT INTO workflows
                   (workflow_id, session_id, name, stages, current_stage, status, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (
                    wf.workflow_id, wf.session_id, wf.name,
                    json.dumps(wf.stages, ensure_ascii=False),
                    wf.current_stage, wf.status, wf.created_at, wf.updated_at,
                ),
            )
        return wf

    def advance_workflow(
        self,
        workflow_id: str,
        stage_data: Optional[dict] = None,
    ) -> Optional[WorkflowState]:
        """Advance to the next stage in the workflow."""
        wf = self.get_workflow(workflow_id)
        if not wf or wf.status != "running":
            return wf

        # Mark current stage as completed
        for stage in wf.stages:
            if stage["name"] == wf.current_stage:
                stage["status"] = "completed"
                stage["completed_at"] = time.time()
                if stage_data:
                    stage["data"] = stage_data
                break

        # Find next stage
        current_idx = next(
            (i for i, s in enumerate(wf.stages) if s["name"] == wf.current_stage),
            -1,
        )
        if current_idx + 1 < len(wf.stages):
            next_stage = wf.stages[current_idx + 1]
            wf.current_stage = next_stage["name"]
            next_stage["status"] = "running"
            next_stage["started_at"] = time.time()
        else:
            # All stages completed
            wf.status = "completed"
            wf.current_stage = None

        wf.updated_at = time.time()
        self._update_workflow(wf)
        return wf

    def fail_workflow(self, workflow_id: str, error: str = ""):
        """Mark a workflow as failed."""
        wf = self.get_workflow(workflow_id)
        if wf:
            wf.status = "failed"
            wf.updated_at = time.time()
            wf.result = {"error": error}
            self._update_workflow(wf)

    def get_workflow(self, workflow_id: str) -> Optional[WorkflowState]:
        """Get a workflow by ID."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM workflows WHERE workflow_id = ?",
                (workflow_id,),
            ).fetchone()
        if row:
            return self._row_to_workflow(row)
        return None

    def list_workflows(
        self,
        session_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 20,
    ) -> list[dict]:
        """List workflows with optional filters."""
        query = "SELECT * FROM workflows WHERE 1=1"
        params = []
        if session_id:
            query += " AND session_id = ?"
            params.append(session_id)
        if status:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY updated_at DESC LIMIT ?"
        params.append(limit)

        with self._get_conn() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._row_to_workflow(r).to_dict() for r in rows]

    def complete_workflow(self, workflow_id: str, result: Optional[dict] = None):
        """Mark a workflow as completed with optional result."""
        wf = self.get_workflow(workflow_id)
        if wf:
            wf.status = "completed"
            wf.updated_at = time.time()
            wf.result = result
            self._update_workflow(wf)

    # --- Cleanup ---

    def cleanup(self, retention_days: int = 3):
        """Remove old checkpoints and completed workflows."""
        cutoff = time.time() - (retention_days * 86400)
        with self._get_conn() as conn:
            r1 = conn.execute("DELETE FROM checkpoints WHERE created_at < ?", (cutoff,))
            r2 = conn.execute(
                "DELETE FROM workflows WHERE updated_at < ? AND status IN ('completed', 'failed')",
                (cutoff,),
            )
            total = r1.rowcount + r2.rowcount
            if total > 0:
                _logger.info(f"[checkpoint] Cleaned up {total} old records")

    # --- Helpers ---

    def _update_workflow(self, wf: WorkflowState):
        with self._get_conn() as conn:
            conn.execute(
                """UPDATE workflows
                   SET stages=?, current_stage=?, status=?, updated_at=?, result=?
                   WHERE workflow_id=?""",
                (
                    json.dumps(wf.stages, ensure_ascii=False),
                    wf.current_stage, wf.status, wf.updated_at,
                    json.dumps(wf.result, ensure_ascii=False) if wf.result else None,
                    wf.workflow_id,
                ),
            )

    @staticmethod
    def _row_to_checkpoint(row) -> Checkpoint:
        d = dict(row)
        d["state"] = json.loads(d["state"])
        if d.get("metadata"):
            try:
                d["metadata"] = json.loads(d["metadata"])
            except (json.JSONDecodeError, TypeError):
                d["metadata"] = None
        return Checkpoint(**d)

    @staticmethod
    def _row_to_workflow(row) -> WorkflowState:
        d = dict(row)
        d["stages"] = json.loads(d["stages"])
        if d.get("result"):
            try:
                d["result"] = json.loads(d["result"])
            except (json.JSONDecodeError, TypeError):
                d["result"] = None
        return WorkflowState(**d)


# ---------------------------------------------------------------------------
# Global instance
# ---------------------------------------------------------------------------

_checkpoint_manager: Optional[CheckpointManager] = None


def get_checkpoint_manager() -> CheckpointManager:
    global _checkpoint_manager
    if _checkpoint_manager is None:
        _checkpoint_manager = CheckpointManager()
    return _checkpoint_manager
