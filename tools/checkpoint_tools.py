"""Tools: checkpoint — save/load agent state, workflow management."""


def register(registry):
    from agent.checkpoint import get_checkpoint_manager

    def handle_save_checkpoint(**args):
        mgr = get_checkpoint_manager()
        cp = mgr.save_checkpoint(
            session_id=args["session_id"],
            stage=args.get("stage", "default"),
            state=args.get("state", {}),
            metadata=args.get("metadata", {}),
        )
        return f"检查点已保存: {cp.checkpoint_id} (stage={cp.stage})"

    def handle_load_checkpoint(**args):
        mgr = get_checkpoint_manager()
        cp = mgr.load_checkpoint(args["checkpoint_id"])
        if not cp:
            return f"未找到检查点 {args['checkpoint_id']}。"
        return (
            f"检查点 {cp.checkpoint_id}:\n"
            f"  session={cp.session_id} stage={cp.stage}\n"
            f"  state={cp.state}\n"
            f"  metadata={cp.metadata}\n"
            f"  created={cp.created_at}"
        )

    def handle_list_checkpoints(**args):
        mgr = get_checkpoint_manager()
        cps = mgr.list_checkpoints(
            session_id=args["session_id"],
            limit=args.get("limit", 10),
        )
        if not cps:
            return f"会话 {args['session_id']} 没有检查点。"
        lines = []
        for c in cps:
            lines.append(
                f"  [{c['checkpoint_id']}] stage={c['stage']} | "
                f"{c['created_at']} | meta={c.get('metadata', {})}"
            )
        return f"检查点列表 ({len(lines)}):\n" + "\n".join(lines)

    def handle_create_workflow(**args):
        mgr = get_checkpoint_manager()
        wf = mgr.create_workflow(
            session_id=args["session_id"],
            name=args["name"],
            stages=args.get("stages", []),
        )
        return f"工作流已创建: {wf.workflow_id} (name={wf.name}, stages={len(wf.stages)})"

    def handle_advance_workflow(**args):
        mgr = get_checkpoint_manager()
        wf = mgr.advance_workflow(
            workflow_id=args["workflow_id"],
            data=args.get("data", {}),
        )
        if not wf:
            return f"未找到工作流 {args['workflow_id']}。"
        return (
            f"工作流 {wf.workflow_id} 已推进:\n"
            f"  当前阶段: {wf.current_stage}\n"
            f"  状态: {wf.status}\n"
            f"  总阶段数: {len(wf.stages)}"
        )

    def handle_workflow_status(**args):
        mgr = get_checkpoint_manager()
        wf = mgr.get_workflow(args["workflow_id"])
        if not wf:
            return f"未找到工作流 {args['workflow_id']}。"
        lines = [
            f"工作流 {wf.workflow_id}:",
            f"  名称: {wf.name}",
            f"  状态: {wf.status}",
            f"  当前阶段: {wf.current_stage}",
        ]
        for i, s in enumerate(wf.stages):
            marker = " ←" if s.get("name") == wf.current_stage else ""
            lines.append(f"  [{i+1}] {s.get('name', '?')} — {s.get('status', '?')}{marker}")
        return "\n".join(lines)

    def handle_list_workflows(**args):
        mgr = get_checkpoint_manager()
        wfs = mgr.list_workflows(
            session_id=args.get("session_id"),
            status=args.get("status"),
            limit=args.get("limit", 10),
        )
        if not wfs:
            return "没有匹配的工作流。"
        lines = []
        for w in wfs:
            lines.append(
                f"  [{w['workflow_id']}] {w['name']} | {w['status']} | "
                f"stage={w['current_stage']}"
            )
        return f"工作流列表 ({len(lines)}):\n" + "\n".join(lines)

    registry.register(
        name="checkpoint_save",
        description="保存当前智能体状态到检查点，方便后续恢复。",
        parameters={
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "会话ID"},
                "stage": {"type": "string", "description": "阶段名称（默认default）"},
                "state": {"type": "object", "description": "状态数据（JSON对象）"},
                "metadata": {"type": "object", "description": "元数据（可选）"},
            },
            "required": ["session_id"],
        },
        handler=handle_save_checkpoint,
        toolset="checkpoint",
        emoji="💾",
    )
    registry.register(
        name="checkpoint_load",
        description="加载指定的检查点，恢复智能体状态。",
        parameters={
            "type": "object",
            "properties": {
                "checkpoint_id": {"type": "string", "description": "检查点ID"},
            },
            "required": ["checkpoint_id"],
        },
        handler=handle_load_checkpoint,
        toolset="checkpoint",
        emoji="📂",
    )
    registry.register(
        name="checkpoint_list",
        description="列出某个会话的所有检查点。",
        parameters={
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "会话ID"},
                "limit": {"type": "integer", "description": "返回数量（默认10）"},
            },
            "required": ["session_id"],
        },
        handler=handle_list_checkpoints,
        toolset="checkpoint",
        emoji="📋",
    )
    registry.register(
        name="workflow_create",
        description="创建一个新的工作流，定义多个阶段。",
        parameters={
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "会话ID"},
                "name": {"type": "string", "description": "工作流名称"},
                "stages": {"type": "array", "description": "阶段名称列表", "items": {"type": "string"}},
            },
            "required": ["session_id", "name"],
        },
        handler=handle_create_workflow,
        toolset="checkpoint",
        emoji="🚀",
    )
    registry.register(
        name="workflow_advance",
        description="推进工作流到下一个阶段。",
        parameters={
            "type": "object",
            "properties": {
                "workflow_id": {"type": "string", "description": "工作流ID"},
                "data": {"type": "object", "description": "当前阶段的数据（可选）"},
            },
            "required": ["workflow_id"],
        },
        handler=handle_advance_workflow,
        toolset="checkpoint",
        emoji="▶️",
    )
    registry.register(
        name="workflow_status",
        description="查看工作流的详细状态和各阶段进度。",
        parameters={
            "type": "object",
            "properties": {
                "workflow_id": {"type": "string", "description": "工作流ID"},
            },
            "required": ["workflow_id"],
        },
        handler=handle_workflow_status,
        toolset="checkpoint",
        emoji="📊",
    )
    registry.register(
        name="workflow_list",
        description="列出工作流，可按会话和状态过滤。",
        parameters={
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "会话ID（可选）"},
                "status": {"type": "string", "description": "状态过滤（可选）"},
                "limit": {"type": "integer", "description": "返回数量（默认10）"},
            },
        },
        handler=handle_list_workflows,
        toolset="checkpoint",
        emoji="📑",
    )


# AST scanner detection
if False:
    register(None)
