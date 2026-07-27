"""Tools: adaptive learning — tool metrics, failure analysis, dynamic selection."""


def register(registry):
    from agent.adaptive import get_auto_learner

    def handle_tool_metrics(**args):
        learner = get_auto_learner()
        m = learner.get_tool_metrics(args["tool_name"])
        if not m:
            return f"没有工具 {args['tool_name']} 的指标数据。"
        return (
            f"工具 {args['tool_name']} 指标:\n"
            f"  调用次数: {m.get('total_calls', 0)}\n"
            f"  成功率: {m.get('success_rate', 0):.1%}\n"
            f"  平均延迟: {m.get('avg_latency', 0):.0f}ms\n"
            f"  最大延迟: {m.get('max_latency', 0):.0f}ms\n"
            f"  平均成本: ${m.get('avg_cost', 0):.6f}\n"
            f"  失败次数: {m.get('failure_count', 0)}\n"
            f"  最近失败: {m.get('recent_failures', 0)}"
        )

    def handle_top_tools(**args):
        learner = get_auto_learner()
        tools = learner.get_top_tools(
            limit=args.get("limit", 10), min_calls=args.get("min_calls", 5)
        )
        if not tools:
            return "没有足够的工具数据。"
        lines = []
        for t in tools:
            lines.append(
                f"  {t['tool_name']}: calls={t['total_calls']} "
                f"success={t['success_rate']:.1%} "
                f"avg={t.get('avg_latency', 0):.0f}ms"
            )
        return f"最佳工具 ({len(lines)}):\n" + "\n".join(lines)

    def handle_worst_tools(**args):
        learner = get_auto_learner()
        tools = learner.get_worst_tools(
            limit=args.get("limit", 10), min_calls=args.get("min_calls", 5)
        )
        if not tools:
            return "没有足够的工具数据。"
        lines = []
        for t in tools:
            lines.append(
                f"  {t['tool_name']}: calls={t['total_calls']} "
                f"success={t['success_rate']:.1%} "
                f"failures={t.get('failure_count', 0)}"
            )
        return f"最不稳定工具 ({len(lines)}):\n" + "\n".join(lines)

    def handle_failure_patterns(**args):
        learner = get_auto_learner()
        patterns = learner.get_failure_patterns(
            tool_name=args.get("tool_name")
        )
        if not patterns:
            return "没有发现失败模式。"
        lines = []
        for p in patterns[:15]:
            lines.append(
                f"  [{p.get('count', 1)}次] {p['tool_name']}: {p['pattern']}"
            )
        return f"失败模式 ({len(lines)}):\n" + "\n".join(lines)

    def handle_adjustments(**args):
        learner = get_auto_learner()
        adj = learner.get_adjustments(limit=args.get("limit", 20))
        if not adj:
            return "没有策略调整记录。"
        lines = []
        for a in adj:
            lines.append(
                f"  [{a['tool_name']}] {a['trigger']}: "
                f"{a['old_strategy']} → {a['new_strategy']} | "
                f"outcome={a.get('outcome', '?')}"
            )
        return f"策略调整 ({len(lines)}):\n" + "\n".join(lines)

    def handle_tool_weights(**args):
        learner = get_auto_learner()
        weights = learner.get_tool_weights()
        if not weights:
            return "没有工具权重数据。"
        sorted_w = sorted(weights.items(), key=lambda x: -x[1])
        lines = []
        for name, w in sorted_w[:15]:
            bar = "█" * int(w * 20)
            lines.append(f"  {name}: {w:.3f} {bar}")
        return f"工具权重 ({len(lines)}):\n" + "\n".join(lines)

    def handle_all_metrics(**args):
        learner = get_auto_learner()
        metrics = learner.get_all_metrics()
        if not metrics:
            return "没有工具指标数据。"
        lines = []
        for m in sorted(metrics, key=lambda x: -x.get("total_calls", 0))[:20]:
            lines.append(
                f"  {m['tool_name']}: calls={m['total_calls']} "
                f"ok={m['success_rate']:.0%} "
                f"lat={m.get('avg_latency', 0):.0f}ms"
            )
        return f"全部工具指标 ({len(lines)}):\n" + "\n".join(lines)

    registry.register(
        name="adaptive_metrics",
        description="查看某个工具的详细性能指标。",
        parameters={
            "type": "object",
            "properties": {
                "tool_name": {"type": "string", "description": "工具名称"},
            },
            "required": ["tool_name"],
        },
        handler=handle_tool_metrics,
        toolset="adaptive",
        emoji="📈",
    )
    registry.register(
        name="adaptive_top_tools",
        description="查看表现最好的工具排名。",
        parameters={
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "返回数量（默认10）"},
                "min_calls": {"type": "integer", "description": "最小调用次数（默认5）"},
            },
        },
        handler=handle_top_tools,
        toolset="adaptive",
        emoji="🏆",
    )
    registry.register(
        name="adaptive_worst_tools",
        description="查看表现最差的工具排名（需要关注或替换）。",
        parameters={
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "返回数量（默认10）"},
                "min_calls": {"type": "integer", "description": "最小调用次数（默认5）"},
            },
        },
        handler=handle_worst_tools,
        toolset="adaptive",
        emoji="⚠️",
    )
    registry.register(
        name="adaptive_failure_patterns",
        description="查看工具失败模式分析：哪些错误在反复出现。",
        parameters={
            "type": "object",
            "properties": {
                "tool_name": {"type": "string", "description": "工具名称（可选，不填则查全部）"},
            },
        },
        handler=handle_failure_patterns,
        toolset="adaptive",
        emoji="🔬",
    )
    registry.register(
        name="adaptive_adjustments",
        description="查看系统自动做的策略调整记录。",
        parameters={
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "返回数量（默认20）"},
            },
        },
        handler=handle_adjustments,
        toolset="adaptive",
        emoji="🔧",
    )
    registry.register(
        name="adaptive_weights",
        description="查看工具的动态选择权重（系统自动调整）。",
        parameters={"type": "object", "properties": {}},
        handler=handle_tool_weights,
        toolset="adaptive",
        emoji="⚖️",
    )
    registry.register(
        name="adaptive_all_metrics",
        description="查看所有工具的性能指标概览。",
        parameters={
            "type": "object",
            "properties": {},
        },
        handler=handle_all_metrics,
        toolset="adaptive",
        emoji="📊",
    )


# AST scanner detection
if False:
    register(None)
