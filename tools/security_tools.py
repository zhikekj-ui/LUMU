"""Tools: security — audit log queries, RBAC management, command sandbox."""


def register(registry):
    from agent.security import get_audit_logger, get_rbac_manager, CommandSandbox, PermissionLevel

    def handle_audit_recent(**args):
        logger = get_audit_logger()
        rows = logger.get_recent(limit=args.get("limit", 20), action=args.get("action"))
        if not rows:
            return "没有审计记录。"
        lines = []
        for r in rows:
            lines.append(
                f"  [{r['action']}] {r.get('actor', '-')} → {r.get('resource', '-')} | "
                f"{r.get('result', '-')} | {r['timestamp']}"
            )
        return f"最近审计记录 ({len(lines)}):\n" + "\n".join(lines)

    def handle_audit_session(**args):
        logger = get_audit_logger()
        rows = logger.get_session_activity(
            session_id=args["session_id"], limit=args.get("limit", 50)
        )
        if not rows:
            return f"会话 {args['session_id']} 没有活动记录。"
        lines = []
        for r in rows:
            lines.append(
                f"  [{r['action']}] {r.get('resource', '-')} | "
                f"{r.get('result', '-')} | {r['timestamp']}"
            )
        return f"会话 {args['session_id']} 活动 ({len(lines)}):\n" + "\n".join(lines)

    def handle_audit_summary(**args):
        logger = get_audit_logger()
        summary = logger.get_summary(hours=args.get("hours", 24))
        if not summary or not summary.get("total_entries"):
            return "指定时段内没有审计记录。"
        lines = [
            f"  总记录: {summary['total_entries']}",
            f"  工具调用: {summary.get('tool_calls', 0)}",
            f"  文件操作: {summary.get('file_operations', 0)}",
            f"  API调用: {summary.get('api_calls', 0)}",
            f"  错误数: {summary.get('errors', 0)}",
        ]
        by_action = summary.get("by_action", {})
        if by_action:
            lines.append("  按操作:")
            for a, c in sorted(by_action.items(), key=lambda x: -x[1])[:8]:
                lines.append(f"    {a}: {c}")
        return f"审计摘要 (最近{args.get('hours', 24)}h):\n" + "\n".join(lines)

    def handle_check_permission(**args):
        rbac = get_rbac_manager()
        allowed, reason = rbac.can_use_tool(
            session_id=args["session_id"], tool_name=args["tool_name"]
        )
        if allowed:
            return f"会话 {args['session_id']} 可以使用 {args['tool_name']}。"
        return f"会话 {args['session_id']} 不能使用 {args['tool_name']}: {reason}"

    def handle_set_permission(**args):
        rbac = get_rbac_manager()
        level_map = {
            "read_only": PermissionLevel.READ_ONLY,
            "standard": PermissionLevel.STANDARD,
            "admin": PermissionLevel.ADMIN,
            "unrestricted": PermissionLevel.UNRESTRICTED,
        }
        level = level_map.get(args["level"].lower())
        if not level:
            return f"无效权限级别: {args['level']}。可选: {', '.join(level_map.keys())}"
        rbac.set_permission(args["session_id"], level)
        return f"已设置会话 {args['session_id']} 权限为 {args['level']}。"

    def handle_validate_command(**args):
        sandbox = CommandSandbox()
        allowed, reason = sandbox.validate_command(
            args["command"], session_id=args.get("session_id", "")
        )
        if allowed:
            return f"命令允许执行: {args['command'][:80]}"
        return f"命令被阻止: {reason}"

    registry.register(
        name="audit_recent",
        description="查看最近的审计日志记录。",
        parameters={
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "返回数量（默认20）"},
                "action": {"type": "string", "description": "按操作类型过滤（可选）"},
            },
        },
        handler=handle_audit_recent,
        toolset="security",
        emoji="📋",
    )
    registry.register(
        name="audit_session",
        description="查看某个会话的完整活动记录。",
        parameters={
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "会话ID"},
                "limit": {"type": "integer", "description": "返回数量（默认50）"},
            },
            "required": ["session_id"],
        },
        handler=handle_audit_session,
        toolset="security",
        emoji="🔍",
    )
    registry.register(
        name="audit_summary",
        description="查看审计统计摘要：操作数量、错误数等。",
        parameters={
            "type": "object",
            "properties": {
                "hours": {"type": "integer", "description": "统计时段（小时，默认24）"},
            },
        },
        handler=handle_audit_summary,
        toolset="security",
        emoji="📊",
    )
    registry.register(
        name="security_check_permission",
        description="检查某个会话是否有权限使用指定工具。",
        parameters={
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "会话ID"},
                "tool_name": {"type": "string", "description": "工具名称"},
            },
            "required": ["session_id", "tool_name"],
        },
        handler=handle_check_permission,
        toolset="security",
        emoji="🔐",
    )
    registry.register(
        name="security_set_permission",
        description="设置会话的权限级别（read_only/standard/admin/unrestricted）。",
        parameters={
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "会话ID"},
                "level": {"type": "string", "description": "权限级别"},
            },
            "required": ["session_id", "level"],
        },
        handler=handle_set_permission,
        toolset="security",
        emoji="🛡️",
    )
    registry.register(
        name="security_validate_command",
        description="在沙箱中验证命令是否安全可执行。",
        parameters={
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "要验证的终端命令"},
                "session_id": {"type": "string", "description": "会话ID（可选）"},
            },
            "required": ["command"],
        },
        handler=handle_validate_command,
        toolset="security",
        emoji="🔒",
    )


# AST scanner detection
if False:
    register(None)
