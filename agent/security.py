"""Security — RBAC, audit logging, and command sandboxing.

Provides:
- AuditLogger: standardized audit trail for all agent actions
- RBACManager: role-based access control for tool permissions
- CommandSandbox: whitelist/blacklist for terminal commands
- Permission levels: read-only, standard, admin, unrestricted
- Audit events: tool calls, file operations, API calls, errors

Design: audit log in SQLite (append-only), RBAC rules in memory with
optional persistence. Command sandbox uses pattern matching.
"""
from core.logging_config import get_logger
_logger = get_logger("agent.security")
import json
import os
import re
import sqlite3
import time
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any, Optional


class PermissionLevel(str, Enum):
    READ_ONLY = "read_only"      # Can only read/search, no modifications
    STANDARD = "standard"        # Can read/write files, limited terminal
    ADMIN = "admin"              # Full tool access except dangerous commands
    UNRESTRICTED = "unrestricted"  # No restrictions


# ---------------------------------------------------------------------------
# Audit Logger
# ---------------------------------------------------------------------------

@dataclass
class AuditEntry:
    """A single audit log entry."""
    entry_id: str
    timestamp: float
    session_id: Optional[str]
    actor: str  # "agent", "user", "system", "cron"
    action: str  # "tool_call", "file_write", "api_call", etc.
    resource: str  # tool name, file path, URL, etc.
    details: Optional[dict] = None
    result: str = "success"  # success, failure, denied
    risk_level: Optional[str] = None
    ip_address: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


class AuditLogger:
    """Append-only audit trail for all agent actions."""

    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            base_dir = os.environ.get("AGENT_BASE_DIR", os.getcwd())
            db_path = os.path.join(base_dir, "data", "audit.db")
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db_path = db_path
        self._init_db()
        _logger.info("[audit] AuditLogger initialized")

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self):
        with self._get_conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS audit_log (
                    entry_id    TEXT PRIMARY KEY,
                    timestamp   REAL NOT NULL,
                    session_id  TEXT,
                    actor       TEXT NOT NULL,
                    action      TEXT NOT NULL,
                    resource    TEXT NOT NULL,
                    details     TEXT,
                    result      TEXT DEFAULT 'success',
                    risk_level  TEXT,
                    ip_address  TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_audit_time
                    ON audit_log(timestamp);
                CREATE INDEX IF NOT EXISTS idx_audit_action
                    ON audit_log(action);
                CREATE INDEX IF NOT EXISTS idx_audit_session
                    ON audit_log(session_id);
                CREATE INDEX IF NOT EXISTS idx_audit_actor
                    ON audit_log(actor);
            """)

    def log(
        self,
        action: str,
        resource: str,
        actor: str = "agent",
        session_id: Optional[str] = None,
        details: Optional[dict] = None,
        result: str = "success",
        risk_level: Optional[str] = None,
        ip_address: Optional[str] = None,
    ) -> AuditEntry:
        """Log an audit event."""
        import uuid
        entry = AuditEntry(
            entry_id=str(uuid.uuid4())[:12],
            timestamp=time.time(),
            session_id=session_id,
            actor=actor,
            action=action,
            resource=resource,
            details=details,
            result=result,
            risk_level=risk_level,
            ip_address=ip_address,
        )
        with self._get_conn() as conn:
            conn.execute(
                """INSERT INTO audit_log
                   (entry_id, timestamp, session_id, actor, action, resource,
                    details, result, risk_level, ip_address)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    entry.entry_id, entry.timestamp, entry.session_id,
                    entry.actor, entry.action, entry.resource,
                    json.dumps(details, ensure_ascii=False, default=str) if details else None,
                    entry.result, entry.risk_level, entry.ip_address,
                ),
            )
        return entry

    def log_tool_call(
        self,
        tool_name: str,
        args: dict,
        result: str = "success",
        session_id: Optional[str] = None,
        risk_level: Optional[str] = None,
    ):
        """Convenience: log a tool call."""
        self.log(
            action="tool_call",
            resource=tool_name,
            details={"args": args},
            result=result,
            session_id=session_id,
            risk_level=risk_level,
        )

    def log_file_operation(
        self,
        operation: str,  # read, write, delete
        path: str,
        session_id: Optional[str] = None,
        result: str = "success",
    ):
        """Convenience: log a file operation."""
        self.log(
            action=f"file_{operation}",
            resource=path,
            result=result,
            session_id=session_id,
        )

    def log_api_call(
        self,
        method: str,
        url: str,
        status_code: Optional[int] = None,
        session_id: Optional[str] = None,
    ):
        """Convenience: log an external API call."""
        self.log(
            action="api_call",
            resource=f"{method} {url}",
            details={"status_code": status_code},
            session_id=session_id,
        )

    # --- Query API ---

    def get_recent(self, limit: int = 100, action: Optional[str] = None) -> list[dict]:
        """Get recent audit entries."""
        query = "SELECT * FROM audit_log"
        params = []
        if action:
            query += " WHERE action = ?"
            params.append(action)
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        with self._get_conn() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def get_session_activity(self, session_id: str, limit: int = 100) -> list[dict]:
        """Get all activity for a specific session."""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM audit_log WHERE session_id = ? ORDER BY timestamp DESC LIMIT ?",
                (session_id, limit),
            ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def get_summary(self, hours: int = 24) -> dict:
        """Get activity summary for a time period."""
        cutoff = time.time() - (hours * 3600)
        with self._get_conn() as conn:
            total = conn.execute(
                "SELECT COUNT(*) as count FROM audit_log WHERE timestamp > ?",
                (cutoff,),
            ).fetchone()["count"]
            by_action = conn.execute(
                """SELECT action, COUNT(*) as count FROM audit_log
                   WHERE timestamp > ? GROUP BY action ORDER BY count DESC""",
                (cutoff,),
            ).fetchall()
            by_actor = conn.execute(
                """SELECT actor, COUNT(*) as count FROM audit_log
                   WHERE timestamp > ? GROUP BY actor ORDER BY count DESC""",
                (cutoff,),
            ).fetchall()
            errors = conn.execute(
                "SELECT COUNT(*) as count FROM audit_log WHERE timestamp > ? AND result != 'success'",
                (cutoff,),
            ).fetchone()["count"]

        return {
            "total_events": total,
            "by_action": {r["action"]: r["count"] for r in by_action},
            "by_actor": {r["actor"]: r["count"] for r in by_actor},
            "errors": errors,
            "period_hours": hours,
        }

    def cleanup(self, retention_days: int = 30):
        """Remove old audit entries (default 30 day retention)."""
        cutoff = time.time() - (retention_days * 86400)
        with self._get_conn() as conn:
            result = conn.execute("DELETE FROM audit_log WHERE timestamp < ?", (cutoff,))
            if result.rowcount > 0:
                _logger.info(f"[audit] Cleaned up {result.rowcount} old entries")

    @staticmethod
    def _row_to_dict(row) -> dict:
        d = dict(row)
        if d.get("details"):
            try:
                d["details"] = json.loads(d["details"])
            except (json.JSONDecodeError, TypeError):
                pass
        return d


# ---------------------------------------------------------------------------
# RBAC Manager
# ---------------------------------------------------------------------------

# Default tool permissions by level
DEFAULT_PERMISSIONS = {
    PermissionLevel.READ_ONLY: {
        "allowed_tools": {
            "read_file", "list_dir", "search_files", "system_status",
            "get_current_time", "web_search", "browser_extract_content",
            "memory_search", "memory_semantic_search", "get_lessons",
            "session_list", "session_search", "task_list", "vision_analyze",
        },
        "denied_tools": set(),
    },
    PermissionLevel.STANDARD: {
        "allowed_tools": None,  # None means "all except denied"
        "denied_tools": {
            "terminal",  # No direct terminal access
        },
    },
    PermissionLevel.ADMIN: {
        "allowed_tools": None,  # All tools
        "denied_tools": set(),
    },
    PermissionLevel.UNRESTRICTED: {
        "allowed_tools": None,
        "denied_tools": set(),
    },
}


class RBACManager:
    """Role-based access control for tool permissions."""

    def __init__(self):
        self._session_permissions: dict[str, PermissionLevel] = {}
        self._custom_rules: dict[str, set] = defaultdict(set)  # tool_name -> denied sessions
        self._audit = AuditLogger()
        _logger.info("[rbac] RBACManager initialized")

    def set_permission(self, session_id: str, level: PermissionLevel):
        """Set permission level for a session."""
        self._session_permissions[session_id] = level

    def get_permission(self, session_id: str) -> PermissionLevel:
        """Get permission level for a session."""
        return self._session_permissions.get(session_id, PermissionLevel.STANDARD)

    def can_use_tool(self, session_id: str, tool_name: str) -> tuple[bool, str]:
        """Check if a session can use a specific tool.

        Returns: (allowed, reason)
        """
        level = self.get_permission(session_id)
        perms = DEFAULT_PERMISSIONS.get(level, DEFAULT_PERMISSIONS[PermissionLevel.STANDARD])

        # Check custom deny rules
        if session_id in self._custom_rules.get(tool_name, set()):
            self._audit.log(
                action="access_denied",
                resource=tool_name,
                session_id=session_id,
                details={"reason": "custom_deny_rule", "level": level.value},
                result="denied",
            )
            return False, f"Tool {tool_name} denied by custom rule"

        # Check allowed list
        if perms["allowed_tools"] is not None:
            if tool_name not in perms["allowed_tools"]:
                self._audit.log(
                    action="access_denied",
                    resource=tool_name,
                    session_id=session_id,
                    details={"reason": "not_in_allowed_list", "level": level.value},
                    result="denied",
                )
                return False, f"Tool {tool_name} not allowed for {level.value} level"

        # Check denied list
        if tool_name in perms["denied_tools"]:
            self._audit.log(
                action="access_denied",
                resource=tool_name,
                session_id=session_id,
                details={"reason": "in_denied_list", "level": level.value},
                result="denied",
            )
            return False, f"Tool {tool_name} denied for {level.value} level"

        return True, "ok"

    def deny_tool(self, tool_name: str, session_id: str):
        """Add a custom deny rule for a specific session."""
        self._custom_rules[tool_name].add(session_id)

    def allow_tool(self, tool_name: str, session_id: str):
        """Remove a custom deny rule."""
        self._custom_rules[tool_name].discard(session_id)


# ---------------------------------------------------------------------------
# Command Sandbox
# ---------------------------------------------------------------------------

class CommandSandbox:
    """Whitelist/blacklist for terminal commands."""

    # Dangerous patterns that should always be blocked (hard-block, never executed)
    # 注意：rm -rf / 与 chmod 777 / 只拦截"作用于根文件系统"（以 \s|$|;|&|\" 结尾），
    # 避免误伤 rm -rf /tmp/xxx 这类正常清理。
    BLOCKED_PATTERNS = [
        r"rm\s+-rf\s+/(?:\s|$|;|&|\")",   # rm -rf / (root only)
        r"rm\s+-rf\s+~(?:/|\s|$|;|&)",     # rm -rf ~ (home)
        r"mkfs\.",                          # Format filesystem
        r"dd\s+if=.*of=/dev/",              # dd to device
        r">\s*/dev/sd",                     # Write to device
        r"chmod\s+-R\s+777\s+/(?:\s|$|;|&|\")",  # Recursive chmod 777 on root
        r":\(\)\s*\{",                      # Fork bomb
        r"curl.*\|\s*sh",                   # Pipe curl to sh
        r"wget.*\|\s*sh",                   # Pipe wget to sh
        r"\bshutdown\b",                     # Power off
        r"\breboot\b",                       # Reboot
        r"\bpoweroff\b",                     # Power off
        r"\bhalt\b",                        # Halt
    ]

    # Commands that require admin level
    ADMIN_COMMANDS = [
        "sudo", "apt", "yum", "dnf", "pacman",
        "systemctl", "service", "docker",
        "iptables", "ufw",
    ]

    # 默认白名单（TERMINAL_POLICY=whitelist 且未配置 TERMINAL_ALLOWED 时生效）
    DEFAULT_WHITELIST = (
        "ls,cat,pwd,echo,printf,head,tail,wc,sort,uniq,grep,fgrep,egrep,find,xargs,"
        "awk,sed,cut,tr,date,whoami,env,which,python,python3,pip,pip3,git,make,cmake,"
        "node,npm,yarn,mkdir,touch,cp,mv,ln,tar,gzip,gunzip,unzip,curl,wget,ssh,scp,"
        "rsync,ping,dig,nslookup,ps,top,df,du,free,uptime,jq"
    )

    def __init__(self, permission_level: PermissionLevel = PermissionLevel.STANDARD, whitelist: Optional[list] = None):
        self._level = permission_level
        self._blocked_patterns = [re.compile(p, re.IGNORECASE) for p in self.BLOCKED_PATTERNS]
        self._whitelist = set(whitelist) if whitelist else None
        self._audit = AuditLogger()

    def validate_command(self, command: str, session_id: str = "") -> tuple[bool, str]:
        """Validate a terminal command.

        Returns: (allowed, reason)
        """
        # 0. 白名单（仅 whitelist 策略启用）：首 token 必须在白名单内
        if self._whitelist is not None:
            token = command.strip().split()[0] if command.strip() else ""
            if token not in self._whitelist:
                self._audit.log(
                    action="command_blocked",
                    resource=command,
                    session_id=session_id,
                    details={"reason": "not_in_whitelist", "token": token},
                    result="denied",
                    risk_level="high",
                )
                return False, f"命令 '{token}' 不在白名单，已拦截"

        # 1. Always block dangerous patterns
        for pattern in self._blocked_patterns:
            if pattern.search(command):
                self._audit.log(
                    action="command_blocked",
                    resource=command,
                    session_id=session_id,
                    details={"reason": "dangerous_pattern", "pattern": pattern.pattern},
                    result="denied",
                    risk_level="critical",
                )
                return False, f"Command blocked: matches dangerous pattern"

        # Check admin commands
        if self._level not in (PermissionLevel.ADMIN, PermissionLevel.UNRESTRICTED):
            for admin_cmd in self.ADMIN_COMMANDS:
                if command.startswith(admin_cmd) or f" {admin_cmd} " in command:
                    self._audit.log(
                        action="command_restricted",
                        resource=command,
                        session_id=session_id,
                        details={"reason": "requires_admin", "command": admin_cmd},
                        result="denied",
                        risk_level="high",
                    )
                    return False, f"Command '{admin_cmd}' requires admin permission"

        return True, "ok"


# ---------------------------------------------------------------------------
# Global instances
# ---------------------------------------------------------------------------

_audit_logger: Optional[AuditLogger] = None
_rbac_manager: Optional[RBACManager] = None


def get_audit_logger() -> AuditLogger:
    global _audit_logger
    if _audit_logger is None:
        _audit_logger = AuditLogger()
    return _audit_logger


def get_rbac_manager() -> RBACManager:
    global _rbac_manager
    if _rbac_manager is None:
        _rbac_manager = RBACManager()
    return _rbac_manager


# ---------------------------------------------------------------------------
# Command sandbox singleton (reads TERMINAL_POLICY / TERMINAL_ALLOWED)
# ---------------------------------------------------------------------------

_command_sandbox: Optional["CommandSandbox"] = None


def get_command_sandbox() -> "CommandSandbox":
    """Return a process-wide CommandSandbox instance.

    Env:
      TERMINAL_POLICY  blacklist (default) | whitelist | admin
        - blacklist: 仅拦截 BLOCKED_PATTERNS + 管理员命令（非 admin 级别）
        - whitelist: 在上者基础上，额外要求命令首 token 命中白名单
        - admin:     允许管理员命令（但仍拦截 BLOCKED_PATTERNS）
      TERMINAL_ALLOWED  逗号分隔的白名单命令（whitelist 策略下生效；
                        缺省时使用 CommandSandbox.DEFAULT_WHITELIST）
    """
    global _command_sandbox
    if _command_sandbox is None:
        policy = os.getenv("TERMINAL_POLICY", "blacklist").lower()
        allowed = os.getenv("TERMINAL_ALLOWED", "").strip()
        wl = [c.strip() for c in allowed.split(",") if c.strip()] if allowed else None
        if policy == "whitelist" and not wl:
            wl = [c.strip() for c in CommandSandbox.DEFAULT_WHITELIST.split(",") if c.strip()]
        lvl = PermissionLevel.ADMIN if policy == "admin" else PermissionLevel.STANDARD
        _command_sandbox = CommandSandbox(permission_level=lvl, whitelist=wl)
    return _command_sandbox
