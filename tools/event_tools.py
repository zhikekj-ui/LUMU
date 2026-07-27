"""Tools: event bus — event queries, webhook trigger management."""


def register(registry):
    from agent.event_bus import get_event_bus

    def handle_recent_events(**args):
        bus = get_event_bus()
        events = bus.get_recent_events(
            event_type=args.get("event_type"),
            limit=args.get("limit", 20),
        )
        if not events:
            return "没有匹配的事件。"
        lines = []
        for e in events:
            lines.append(
                f"  [{e['event_type']}] {e['source']} | "
                f"{e.get('session_id', '-')} | {e['timestamp']}"
            )
        return f"最近事件 ({len(lines)}):\n" + "\n".join(lines)

    def handle_event_summary(**args):
        bus = get_event_bus()
        summary = bus.get_event_summary(hours=args.get("hours", 24))
        if not summary or not summary.get("total_events"):
            return "指定时段内没有事件。"
        lines = [f"  总事件数: {summary['total_events']}"]
        by_type = summary.get("by_type", {})
        for t, c in sorted(by_type.items(), key=lambda x: -x[1])[:10]:
            lines.append(f"  {t}: {c}")
        return f"事件统计 (最近{args.get('hours', 24)}h):\n" + "\n".join(lines)

    def handle_list_webhooks(**args):
        bus = get_event_bus()
        triggers = bus.list_webhook_triggers()
        if not triggers:
            return "没有配置Webhook触发器。"
        lines = []
        for t in triggers:
            lines.append(
                f"  [{t['id']}] {t['event_pattern']} → {t['url']} "
                f"(active={t.get('active', True)})"
            )
        return f"Webhook触发器 ({len(lines)}):\n" + "\n".join(lines)

    def handle_register_webhook(**args):
        bus = get_event_bus()
        tid = bus.register_webhook_trigger(
            event_pattern=args["event_pattern"],
            url=args["url"],
            description=args.get("description", ""),
        )
        return f"已注册Webhook触发器 ID={tid}: {args['event_pattern']} → {args['url']}"

    def handle_delete_webhook(**args):
        bus = get_event_bus()
        ok = bus.delete_webhook_trigger(args["trigger_id"])
        if ok:
            return f"已删除Webhook触发器 {args['trigger_id']}。"
        return f"删除失败：触发器不存在。"

    registry.register(
        name="event_recent",
        description="查看最近的事件记录，可按类型过滤。",
        parameters={
            "type": "object",
            "properties": {
                "event_type": {"type": "string", "description": "事件类型（可选）"},
                "limit": {"type": "integer", "description": "返回数量（默认20）"},
            },
        },
        handler=handle_recent_events,
        toolset="events",
        emoji="📡",
    )
    registry.register(
        name="event_summary",
        description="查看事件统计：各类事件的数量分布。",
        parameters={
            "type": "object",
            "properties": {
                "hours": {"type": "integer", "description": "统计时段（小时，默认24）"},
            },
        },
        handler=handle_event_summary,
        toolset="events",
        emoji="📊",
    )
    registry.register(
        name="webhook_list",
        description="列出所有已注册的Webhook触发器。",
        parameters={"type": "object", "properties": {}},
        handler=handle_list_webhooks,
        toolset="events",
        emoji="🔗",
    )
    registry.register(
        name="webhook_register",
        description="注册一个新的Webhook触发器：当事件匹配时调用指定URL。",
        parameters={
            "type": "object",
            "properties": {
                "event_pattern": {"type": "string", "description": "事件匹配模式（如 'tool.*' 或 'error'）"},
                "url": {"type": "string", "description": "回调URL"},
                "description": {"type": "string", "description": "描述（可选）"},
            },
            "required": ["event_pattern", "url"],
        },
        handler=handle_register_webhook,
        toolset="events",
        emoji="🔔",
    )
    registry.register(
        name="webhook_delete",
        description="删除一个Webhook触发器。",
        parameters={
            "type": "object",
            "properties": {
                "trigger_id": {"type": "integer", "description": "触发器ID"},
            },
            "required": ["trigger_id"],
        },
        handler=handle_delete_webhook,
        toolset="events",
        emoji="🗑️",
    )


# AST scanner detection
if False:
    register(None)
