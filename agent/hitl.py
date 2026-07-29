"""Human-in-the-loop — approval gates, feedback loops, and intervention mechanisms.

Provides:
- ApprovalGate: pause execution for dangerous operations, wait for user approval
- FeedbackLoop: capture user corrections and feed them back into agent behavior
- RiskClassifier: automatically classify tool calls by risk level
- PendingAction: queue of actions awaiting human approval
- Auto-escalation: if approval times out, take safe default action

Risk levels:
- LOW: read-only operations (list files, search, get status) — auto-approve
- MEDIUM: write operations (create/edit files, send messages) — log only
- HIGH: destructive operations (delete files, execute unknown code, send emails) — require approval
- CRITICAL: irreversible operations (drop database, transfer money) — require approval + confirmation

Design: approval state stored in SQLite, queryable via API endpoints.
"""
from core.logging_config import get_logger
_logger = get_logger("agent.hitl")
import json
import os
import sqlite3
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional, Callable


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    TIMEOUT = "timeout"


# ---------------------------------------------------------------------------
# Risk classifier
# ---------------------------------------------------------------------------

# Default risk classifications for common tools
DEFAULT_RISK_MAP: dict[str, RiskLevel] = {
    # Low risk — read-only
    "read_file": RiskLevel.LOW,
    "list_dir": RiskLevel.LOW,
    "search_files": RiskLevel.LOW,
    "system_status": RiskLevel.LOW,
    "get_current_time": RiskLevel.LOW,
    "web_search": RiskLevel.LOW,
    "browser_extract_content": RiskLevel.LOW,
    "memory_search": RiskLevel.LOW,
    "memory_semantic_search": RiskLevel.LOW,
    "get_lessons": RiskLevel.LOW,
    "session_list": RiskLevel.LOW,
    "session_search": RiskLevel.LOW,
    "task_list": RiskLevel.LOW,

    # Medium risk — write but reversible
    "write_file": RiskLevel.MEDIUM,
    "edit_file": RiskLevel.MEDIUM,
    "memory_save": RiskLevel.MEDIUM,
    "memory_record_event": RiskLevel.MEDIUM,
    "skill_save": RiskLevel.MEDIUM,
    "task_create": RiskLevel.MEDIUM,
    "task_update": RiskLevel.MEDIUM,
    "cron_create": RiskLevel.MEDIUM,
    "api_request": RiskLevel.MEDIUM,
    "browser_navigate": RiskLevel.MEDIUM,
    "browser_click": RiskLevel.MEDIUM,
    "browser_type": RiskLevel.MEDIUM,

    # High risk — destructive or irreversible
    # 注意：terminal 改为"按命令内容定级"（见 RiskClassifier.classify）。
    # 良性命令（ls/cat/python 等）按 MEDIUM 放行；命中危险模式的升级为 HIGH/CRITICAL 后挂起审批。
    "terminal": RiskLevel.MEDIUM,
    "delegate_task": RiskLevel.MEDIUM,
    "collab_execute": RiskLevel.MEDIUM,
    "vision_screenshot": RiskLevel.MEDIUM,
}


class RiskClassifier:
    """Classify tool calls by risk level."""

    def __init__(self, custom_rules: Optional[dict[str, RiskLevel]] = None):
        self._rules = {**DEFAULT_RISK_MAP}
        if custom_rules:
            self._rules.update(custom_rules)
        # Patterns in terminal commands that escalate risk
        self._dangerous_patterns = [
            ("rm -rf", RiskLevel.CRITICAL),
            ("rm ", RiskLevel.HIGH),
            ("DROP TABLE", RiskLevel.CRITICAL),
            ("DROP DATABASE", RiskLevel.CRITICAL),
            ("sudo ", RiskLevel.CRITICAL),
            ("chmod 777", RiskLevel.HIGH),
            ("curl.*|.*sh", RiskLevel.HIGH),
            ("wget.*|.*sh", RiskLevel.HIGH),
            ("> /dev/", RiskLevel.CRITICAL),
            ("mkfs", RiskLevel.CRITICAL),
            ("dd if=", RiskLevel.CRITICAL),
            # 系统级危险操作
            ("shutdown", RiskLevel.CRITICAL),
            ("reboot", RiskLevel.CRITICAL),
            ("poweroff", RiskLevel.CRITICAL),
            ("halt", RiskLevel.CRITICAL),
        ]

    # 仅这些工具真正"执行"不受信任的命令/代码 —— 只有它们才按命令内容升级风险。
    # 其它工具（如 approval_check_risk）可能只是"携带"一个 command 字符串作为参数，
    # 不应被误判升级，否则会出现把风险检查工具本身挂起的误报。
    _EXEC_TOOLS = {"terminal", "code_sandbox"}
    _WRITE_TOOLS = {"write_file", "edit_file"}

    def classify(self, tool_name: str, args: Optional[dict] = None) -> RiskLevel:
        """Classify a tool call's risk level."""
        base_risk = self._rules.get(tool_name, RiskLevel.MEDIUM)
        if not args:
            return base_risk

        # 执行类工具：按命令内容升级风险
        if tool_name in self._EXEC_TOOLS and base_risk in (RiskLevel.MEDIUM, RiskLevel.HIGH):
            cmd = args.get("command", "") or args.get("code", "") or ""
            for pattern, escalated_risk in self._dangerous_patterns:
                if pattern.lower() in cmd.lower():
                    return escalated_risk

        # 写文件类工具：按敏感路径升级风险
        if tool_name in self._WRITE_TOOLS and base_risk in (RiskLevel.MEDIUM, RiskLevel.HIGH):
            path = (args.get("path", "") or args.get("file_path", "") or "").lower()
            # 跨平台敏感路径识别：覆盖 Unix / macOS / Windows 系统目录与主目录，
            # 避免白名单仅含 Unix 路径而在 Windows / macOS 上漏判高危写操作。
            home = os.path.expanduser("~").lower().rstrip(os.sep)
            sensitive = [
                "/etc/", "/usr/", "/var/", "/root/", "/system/", "/library/",
                ".env", ".ssh", "credentials", "id_rsa", "id_ed25519", "token",
            ]
            if home:
                sensitive.append(home + os.sep)
            if os.name == "nt":
                windir = os.environ.get("WINDIR", "C:\\Windows").lower().rstrip("\\") + "\\"
                sensitive += [windir, "c:\\program files", "c:\\programdata", "c:\\users\\"]
            for s in sensitive:
                if s and s in path:
                    return RiskLevel.HIGH

        return base_risk


# ---------------------------------------------------------------------------
# Pending action
# ---------------------------------------------------------------------------

@dataclass
class PendingAction:
    """An action awaiting human approval."""
    action_id: str
    session_id: str
    tool_name: str
    tool_args: dict
    risk_level: str
    reason: str
    created_at: float
    status: str = ApprovalStatus.PENDING
    resolved_at: Optional[float] = None
    resolved_by: Optional[str] = None  # "user", "timeout", "auto"
    user_feedback: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def is_expired(self) -> bool:
        """Check if action has exceeded timeout (default 5 minutes)."""
        return time.time() - self.created_at > 300


# ---------------------------------------------------------------------------
# Approval manager
# ---------------------------------------------------------------------------

class ApprovalManager:
    """Manage approval workflow for high-risk operations."""

    def __init__(self, db_path: Optional[str] = None, require_approval: Optional[set] = None):
        if db_path is None:
            base_dir = os.environ.get("AGENT_BASE_DIR", os.getcwd())
            db_path = os.path.join(base_dir, "data", "approvals.db")
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db_path = db_path
        self._classifier = RiskClassifier()
        # Which risk levels require approval
        self._require_approval = require_approval or {RiskLevel.HIGH, RiskLevel.CRITICAL}
        self._init_db()
        # In-memory pending actions for fast lookup
        self._pending: dict[str, PendingAction] = {}
        self._load_pending()
        _logger.info(f"[hitl] ApprovalManager initialized (approval required for: {', '.join(r.value for r in self._require_approval)})")

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self):
        with self._get_conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS pending_actions (
                    action_id   TEXT PRIMARY KEY,
                    session_id  TEXT NOT NULL,
                    tool_name   TEXT NOT NULL,
                    tool_args   TEXT NOT NULL,
                    risk_level  TEXT NOT NULL,
                    reason      TEXT,
                    created_at  REAL NOT NULL,
                    status      TEXT DEFAULT 'pending',
                    resolved_at REAL,
                    resolved_by TEXT,
                    user_feedback TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_pending_status
                    ON pending_actions(status);
                CREATE INDEX IF NOT EXISTS idx_pending_session
                    ON pending_actions(session_id);

                CREATE TABLE IF NOT EXISTS approval_log (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    action_id   TEXT NOT NULL,
                    event       TEXT NOT NULL,
                    details     TEXT,
                    created_at  REAL NOT NULL
                );
            """)

    def _load_pending(self):
        """Load pending actions from DB into memory."""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM pending_actions WHERE status = 'pending'"
            ).fetchall()
        for r in rows:
            action = PendingAction(
                action_id=r["action_id"],
                session_id=r["session_id"],
                tool_name=r["tool_name"],
                tool_args=json.loads(r["tool_args"]),
                risk_level=r["risk_level"],
                reason=r["reason"] or "",
                created_at=r["created_at"],
                status=r["status"],
            )
            self._pending[action.action_id] = action

    # --- Core API ---

    def should_require_approval(self, tool_name: str, args: Optional[dict] = None) -> bool:
        """Check if a tool call requires human approval."""
        risk = self._classifier.classify(tool_name, args)
        return risk in self._require_approval

    def request_approval(
        self,
        session_id: str,
        tool_name: str,
        tool_args: dict,
        reason: str = "",
    ) -> PendingAction:
        """Create a pending approval request."""
        risk = self._classifier.classify(tool_name, tool_args)
        action = PendingAction(
            action_id=str(uuid.uuid4())[:12],
            session_id=session_id,
            tool_name=tool_name,
            tool_args=tool_args,
            risk_level=risk.value,
            reason=reason or f"Risk level: {risk.value}",
            created_at=time.time(),
        )
        self._pending[action.action_id] = action
        self._persist_action(action)
        self._log_event(action.action_id, "created", f"Risk: {risk.value}")
        return action

    def approve(self, action_id: str, feedback: str = "") -> bool:
        """Approve a pending action."""
        action = self._pending.get(action_id)
        if not action or action.status != ApprovalStatus.PENDING:
            return False
        action.status = ApprovalStatus.APPROVED
        action.resolved_at = time.time()
        action.resolved_by = "user"
        action.user_feedback = feedback or None
        self._update_action(action)
        self._log_event(action_id, "approved", feedback)
        return True

    def deny(self, action_id: str, reason: str = "") -> bool:
        """Deny a pending action."""
        action = self._pending.get(action_id)
        if not action or action.status != ApprovalStatus.PENDING:
            return False
        action.status = ApprovalStatus.DENIED
        action.resolved_at = time.time()
        action.resolved_by = "user"
        action.user_feedback = reason or None
        self._update_action(action)
        self._log_event(action_id, "denied", reason)
        return True

    def get_pending(self, session_id: Optional[str] = None) -> list[dict]:
        """Get pending actions, optionally filtered by session."""
        actions = list(self._pending.values())
        if session_id:
            actions = [a for a in actions if a.session_id == session_id]
        # Check for timeouts
        for a in actions:
            if a.is_expired and a.status == ApprovalStatus.PENDING:
                a.status = ApprovalStatus.TIMEOUT
                a.resolved_at = time.time()
                a.resolved_by = "timeout"
                self._update_action(a)
                self._log_event(a.action_id, "timeout", "Auto-expired after 5 minutes")
        return [a.to_dict() for a in actions if a.status == ApprovalStatus.PENDING]

    def get_status(self, action_id: str) -> Optional[dict]:
        """Get the status of a specific action."""
        action = self._pending.get(action_id)
        return action.to_dict() if action else None

    def get_history(self, limit: int = 50) -> list[dict]:
        """Get recent approval history."""
        with self._get_conn() as conn:
            rows = conn.execute(
                """SELECT * FROM pending_actions
                   WHERE status != 'pending'
                   ORDER BY resolved_at DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        results = []
        for r in rows:
            d = dict(r)
            d["tool_args"] = json.loads(d["tool_args"])
            results.append(d)
        return results

    # --- Feedback loop ---

    def record_feedback(
        self,
        session_id: str,
        original_action: str,
        correction: str,
        outcome: str = "corrected",
    ):
        """Record user feedback for learning.

        This feeds into the learning engine to adjust future behavior.
        """
        with self._get_conn() as conn:
            conn.execute(
                """INSERT INTO approval_log (action_id, event, details, created_at)
                   VALUES (?, 'feedback', ?, ?)""",
                (
                    f"feedback_{session_id}",
                    json.dumps({
                        "session_id": session_id,
                        "original_action": original_action,
                        "correction": correction,
                        "outcome": outcome,
                    }, ensure_ascii=False),
                    time.time(),
                ),
            )

    def get_feedback_patterns(self, limit: int = 20) -> list[dict]:
        """Get recurring feedback patterns for the learning engine."""
        with self._get_conn() as conn:
            rows = conn.execute(
                """SELECT details, created_at FROM approval_log
                   WHERE event = 'feedback'
                   ORDER BY created_at DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        results = []
        for r in rows:
            try:
                results.append(json.loads(r["details"]))
            except json.JSONDecodeError:
                pass
        return results

    # --- Persistence ---

    def _persist_action(self, action: PendingAction):
        with self._get_conn() as conn:
            conn.execute(
                """INSERT INTO pending_actions
                   (action_id, session_id, tool_name, tool_args, risk_level,
                    reason, created_at, status)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (
                    action.action_id, action.session_id, action.tool_name,
                    json.dumps(action.tool_args, ensure_ascii=False),
                    action.risk_level, action.reason, action.created_at,
                    action.status,
                ),
            )

    def _update_action(self, action: PendingAction):
        with self._get_conn() as conn:
            conn.execute(
                """UPDATE pending_actions
                   SET status=?, resolved_at=?, resolved_by=?, user_feedback=?
                   WHERE action_id=?""",
                (action.status, action.resolved_at, action.resolved_by,
                 action.user_feedback, action.action_id),
            )

    def _log_event(self, action_id: str, event: str, details: str = ""):
        with self._get_conn() as conn:
            conn.execute(
                "INSERT INTO approval_log (action_id, event, details, created_at) VALUES (?,?,?,?)",
                (action_id, event, details, time.time()),
            )


# ---------------------------------------------------------------------------
# Global instance
# ---------------------------------------------------------------------------

_approval_manager: Optional[ApprovalManager] = None


def get_approval_manager() -> ApprovalManager:
    global _approval_manager
    if _approval_manager is None:
        _approval_manager = ApprovalManager()
    return _approval_manager
