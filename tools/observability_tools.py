"""Tools: observability — trace queries, performance stats, cost analysis."""


def register(registry):
    from agent.tracing import get_tracer

    def handle_recent_traces(**args):
        tracer = get_tracer()
        traces = tracer.get_recent_traces(limit=args.get("limit", 20))
        if not traces:
            return "No traces found."
        lines = []
        for t in traces:
            cost = t.get("total_cost_usd", 0) or 0
            dur = t.get("total_duration_s", 0) or 0
            lines.append(
                f"  [{t['trace_id']}] {t['root_name']} | "
                f"spans={t['span_count']} errors={t['error_count']} | "
                f"{dur:.1f}s | ${cost:.6f}"
            )
        return f"Recent traces ({len(lines)}):\n" + "\n".join(lines)

    def handle_trace_detail(**args):
        tracer = get_tracer()
        spans = tracer.get_trace(args["trace_id"])
        if not spans:
            return f"No spans found for trace {args['trace_id']}."
        lines = []
        for s in spans:
            dur = s.get("duration_ms", 0) or 0
            status = s.get("status", "?")
            indent = "  " if not s.get("parent_span_id") else "    "
            tokens = ""
            if s.get("token_prompt") or s.get("token_completion"):
                tokens = f" tokens={s['token_prompt']}+{s['token_completion']}"
            lines.append(
                f"{indent}[{s['span_id']}] {s['name']} ({s['span_type']}) "
                f"{dur:.0f}ms {status}{tokens}"
            )
            if s.get("error_message"):
                lines.append(f"      ERROR: {s['error_message']}")
        return f"Trace {args['trace_id']} ({len(spans)} spans):\n" + "\n".join(lines)

    def handle_slow_spans(**args):
        tracer = get_tracer()
        spans = tracer.get_slow_spans(
            threshold_ms=args.get("threshold_ms", 5000),
            limit=args.get("limit", 10),
        )
        if not spans:
            return "No slow spans found."
        lines = []
        for s in spans:
            lines.append(f"  {s['name']} ({s['span_type']}): {s['duration_ms']:.0f}ms")
        return f"Slow spans ({len(lines)}):\n" + "\n".join(lines)

    def handle_cost_summary(**args):
        tracer = get_tracer()
        summary = tracer.get_cost_summary(hours=args.get("hours", 24))
        if not summary or not summary.get("total_spans"):
            return "No activity in the specified period."
        return (
            f"Cost summary (last {args.get('hours', 24)}h):\n"
            f"  Total spans: {summary['total_spans']}\n"
            f"  LLM calls: {summary.get('llm_calls', 0)}\n"
            f"  Prompt tokens: {summary.get('total_prompt_tokens', 0)}\n"
            f"  Completion tokens: {summary.get('total_completion_tokens', 0)}\n"
            f"  Total cost: ${summary.get('total_cost_usd', 0):.6f}\n"
            f"  Avg duration: {summary.get('avg_duration_ms', 0):.0f}ms"
        )

    def handle_tool_stats(**args):
        tracer = get_tracer()
        stats = tracer.get_tool_stats(hours=args.get("hours", 24))
        if not stats:
            return "No tool usage data."
        lines = []
        for s in stats[:15]:
            err_rate = (s["errors"] / s["calls"] * 100) if s["calls"] > 0 else 0
            lines.append(
                f"  {s['tool_name']}: {s['calls']} calls, "
                f"avg={s['avg_ms']:.0f}ms max={s['max_ms']:.0f}ms "
                f"errors={s['errors']} ({err_rate:.1f}%)"
            )
        return f"Tool stats (last {args.get('hours', 24)}h):\n" + "\n".join(lines)

    def handle_error_summary(**args):
        tracer = get_tracer()
        errors = tracer.get_error_summary(hours=args.get("hours", 24))
        if not errors:
            return "No errors in the specified period."
        lines = []
        for e in errors[:10]:
            lines.append(f"  [{e['count']}x] {e['name']}: {e['error_message'][:80]}")
        return f"Error summary (last {args.get('hours', 24)}h):\n" + "\n".join(lines)

    registry.register(
        name="trace_recent",
        description="查看最近的执行追踪记录（trace），包含耗时、token消耗和成本。",
        parameters={
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "返回数量（默认20）"},
            },
        },
        handler=handle_recent_traces,
        toolset="observability",
        emoji="📊",
    )
    registry.register(
        name="trace_detail",
        description="查看某个trace的详细span信息，包含每个步骤的耗时和token消耗。",
        parameters={
            "type": "object",
            "properties": {
                "trace_id": {"type": "string", "description": "Trace ID"},
            },
            "required": ["trace_id"],
        },
        handler=handle_trace_detail,
        toolset="observability",
        emoji="🔍",
    )
    registry.register(
        name="trace_slow",
        description="查找执行缓慢的操作（超过阈值的span）。",
        parameters={
            "type": "object",
            "properties": {
                "threshold_ms": {"type": "integer", "description": "慢操作阈值（毫秒，默认5000）"},
                "limit": {"type": "integer", "description": "返回数量（默认10）"},
            },
        },
        handler=handle_slow_spans,
        toolset="observability",
        emoji="🐌",
    )
    registry.register(
        name="trace_cost",
        description="查看成本统计：token消耗、LLM调用次数、总成本。",
        parameters={
            "type": "object",
            "properties": {
                "hours": {"type": "integer", "description": "统计时段（小时，默认24）"},
            },
        },
        handler=handle_cost_summary,
        toolset="observability",
        emoji="💰",
    )
    registry.register(
        name="trace_tool_stats",
        description="查看各工具的使用统计：调用次数、平均耗时、错误率。",
        parameters={
            "type": "object",
            "properties": {
                "hours": {"type": "integer", "description": "统计时段（小时，默认24）"},
            },
        },
        handler=handle_tool_stats,
        toolset="observability",
        emoji="📈",
    )
    registry.register(
        name="trace_errors",
        description="查看最近的错误汇总，按错误类型分组。",
        parameters={
            "type": "object",
            "properties": {
                "hours": {"type": "integer", "description": "统计时段（小时，默认24）"},
            },
        },
        handler=handle_error_summary,
        toolset="observability",
        emoji="❌",
    )


# AST scanner detection
if False:
    register(None)
