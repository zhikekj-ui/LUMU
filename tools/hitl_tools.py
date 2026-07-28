"""Tools: human-in-the-loop — approval management, feedback loop.

安全铁律（2026-07-28）：模型【绝不能】自己批准挂起的操作。
approval_approve 已从模型可调用工具中移除，批准只能走人工 API：
POST /api/approvals/{action_id}/approve（见 api/main.py）。
模型侧保留：查看待审批、拒绝、历史、风险预检。
"""

# 模块级注册表引用，供人工批准后直接执行被挂起的操作
REGISTRY = None


async def approve_and_execute(action_id: str, feedback: str = "") -> str:
    """人工审批通道专用：批准并立即执行被挂起的操作。

    只允许由 API 层（人类操作）调用，绝不注册为模型工具。
    """
    from agent.hitl import get_approval_manager

    mgr = get_approval_manager()
    ok = mgr.approve(action_id, feedback=feedback)
    if not ok:
        return "批准失败：操作不存在或已过期。"
    # 批准后立即执行被挂起的操作（绕过 HITL 二次拦截；
    # 命令仍受 tools/terminal.py 中的 CommandSandbox 约束 —— defense in depth）
    action = mgr.get_status(action_id)
    if action and action.get("status") == "approved":
        tool_name = action.get("tool_name")
        tool_args = action.get("tool_args") or {}
        if REGISTRY is not None and tool_name:
            try:
                result = await REGISTRY.execute(tool_name, tool_args)
                return f"✅ 已批准并执行 {tool_name}（action_id={action_id}）。\n结果：\n{result}"
            except Exception as e:
                return f"✅ 已批准，但执行失败：{e}"
    return f"已批准操作 {action_id}。"


def register(registry):
    global REGISTRY
    REGISTRY = registry
    from agent.hitl import get_approval_manager

    def handle_pending_approvals(**args):
        mgr = get_approval_manager()
        pending = mgr.get_pending()
        if not pending:
            return "没有待审批的操作。"
        lines = []
        for p in pending:
            lines.append(
                f"  [{p['action_id']}] {p['tool_name']} | risk={p.get('risk_level', '?')} | "
                f"session={p.get('session_id', '-')}"
            )
        return f"待审批操作 ({len(lines)}):\n" + "\n".join(lines)

    def handle_deny(**args):
        mgr = get_approval_manager()
        reason = args.get("reason", "")
        ok = mgr.deny(args["action_id"], reason=reason)
        if ok:
            return f"已拒绝操作 {args['action_id']}。" + (f" 原因: {reason}" if reason else "")
        return f"拒绝失败：操作不存在或已过期。"

    def handle_approval_history(**args):
        mgr = get_approval_manager()
        rows = mgr.get_history(limit=args.get("limit", 20))
        if not rows:
            return "暂无审批记录。"
        lines = []
        for r in rows:
            lines.append(
                f"  [{r['action_id']}] {r['tool_name']} → {r.get('status', '?')} | "
                f"risk={r.get('risk_level', '?')}"
            )
        return f"审批历史 ({len(lines)}):\n" + "\n".join(lines)

    def handle_check_risk(**args):
        mgr = get_approval_manager()
        tool_name = args["tool_name"]
        # Build args dict for classifier
        call_args = {}
        if args.get("command"):
            call_args["command"] = args["command"]
        if args.get("file_path"):
            call_args["file_path"] = args["file_path"]
        needs_approval = mgr.should_require_approval(tool_name, call_args)
        # Also get the risk level from classifier
        risk = mgr._classifier.classify(tool_name, call_args)
        if needs_approval:
            return f"工具 {tool_name} 需要审批（风险等级: {risk.value}）。"
        return f"工具 {tool_name} 无需审批（风险等级: {risk.value}），可直接执行。"

    def handle_feedback_patterns(**args):
        mgr = get_approval_manager()
        patterns = mgr.get_feedback_patterns(limit=args.get("limit", 10))
        if not patterns:
            return "暂无反馈模式数据。"
        lines = []
        for p in patterns:
            lines.append(f"  {p.get('details', '?')[:100]}")
        return f"反馈模式 ({len(lines)}):\n" + "\n".join(lines)

    registry.register(
        name="approval_pending",
        description="查看当前所有待审批的高风险操作。注意：批准只能由人类在审批接口完成，你不能也不应尝试自行批准；请告知用户等待人工审批。",
        parameters={"type": "object", "properties": {}},
        handler=handle_pending_approvals,
        toolset="hitl",
        emoji="⏳",
    )
    # 【安全】approval_approve 已移除：模型不能自己批准挂起操作，
    # 批准只能由人类通过 POST /api/approvals/{action_id}/approve 完成。
    registry.register(
        name="approval_deny",
        description="拒绝一个待审批的操作。",
        parameters={
            "type": "object",
            "properties": {
                "action_id": {"type": "string", "description": "操作ID"},
                "reason": {"type": "string", "description": "拒绝原因（可选）"},
            },
            "required": ["action_id"],
        },
        handler=handle_deny,
        toolset="hitl",
        emoji="❌",
    )
    registry.register(
        name="approval_history",
        description="查看审批历史记录。",
        parameters={
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "返回数量（默认20）"},
            },
        },
        handler=handle_approval_history,
        toolset="hitl",
        emoji="📋",
    )
    registry.register(
        name="approval_check_risk",
        description="检查某个工具或命令的风险等级，判断是否需要审批。",
        parameters={
            "type": "object",
            "properties": {
                "tool_name": {"type": "string", "description": "工具名称"},
                "command": {"type": "string", "description": "终端命令（可选）"},
                "file_path": {"type": "string", "description": "文件路径（可选）"},
            },
            "required": ["tool_name"],
        },
        handler=handle_check_risk,
        toolset="hitl",
        emoji="⚠️",
    )
    registry.register(
        name="approval_feedback_patterns",
        description="查看用户反馈模式：哪些操作经常被批准/拒绝。",
        parameters={
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "返回数量（默认10）"},
            },
        },
        handler=handle_feedback_patterns,
        toolset="hitl",
        emoji="🔄",
    )


# AST scanner detection
if False:
    register(None)
