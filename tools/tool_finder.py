"""tool_find — 按需搜索并激活扩展工具（核心工具常驻，其余搜索后可用）。"""

REGISTRY = None


def register(registry):
    global REGISTRY
    REGISTRY = registry
    registry.register(
        name="tool_find",
        description=(
            "Search and ACTIVATE additional tools by keyword. Core tools (terminal/file/"
            "memory/skills/approval/sandbox/web_search/time) are always available. When you "
            "need other capabilities — charts, browser automation, RAG, knowledge base, cron "
            "jobs, API calls, sessions, checkpoints, TTS, vision, tracing, provider config, "
            "team collaboration — call this FIRST with a keyword (Chinese or English), then "
            "the matching tools become callable in your next step."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Keyword describing the capability you need, e.g. 'chart', '浏览器', 'rag', 'cron', 'api', '知识库'",
                },
            },
            "required": ["query"],
        },
        handler=find_tools,
        toolset="system",
        emoji="🧰",
    )


def find_tools(query: str) -> str:
    try:
        from tools.exposure import activate_toolsets, CORE_TOOLSETS, get_exposed_toolsets
        if REGISTRY is None:
            return "Tool registry unavailable."
        q = (query or "").strip().lower()
        if not q:
            return "请提供搜索关键词。"
        # 中文关键词 → 工具集别名
        aliases = {
            "图表": "visualization", "画图": "visualization", "chart": "visualization",
            "浏览器": "browser", "网页": "browser",
            "知识库": "knowledge", "知识": "knowledge",
            "定时": "cron", "计划任务": "cron",
            "语音": "tts_stt", "朗读": "tts_stt",
            "视觉": "vision", "截图": "vision", "图片": "vision",
            "会话": "session", "任务": "session",
            "团队": "orchestration", "协作": "orchestration", "委派": "orchestration",
            "接口": "api", "请求": "api",
            "检索": "rag", "文档问答": "rag",
            "追踪": "observability", "耗时": "observability",
            "学习": "learning", "教训": "learning",
            "审计": "security", "权限": "security",
            "模型": "provider", "切换模型": "provider",
            "检查点": "checkpoint", "工作流": "checkpoint",
            "事件": "events", "推理": "reasoning", "自适应": "adaptive",
        }
        hit_sets: set[str] = set()
        for k, v in aliases.items():
            if k in q:
                hit_sets.add(v)
        # 按工具名/描述/工具集名匹配
        for t in REGISTRY.list_tools():
            if t.toolset in CORE_TOOLSETS:
                continue
            hay = f"{t.name} {t.description} {t.toolset}".lower()
            if q in hay or t.toolset == q:
                hit_sets.add(t.toolset)
        if not hit_sets:
            all_sets = sorted(set(t.toolset for t in REGISTRY.list_tools()) - CORE_TOOLSETS)
            return f"未找到匹配 '{query}' 的工具。可激活的工具集：{', '.join(all_sets)}"
        activated = activate_toolsets(sorted(hit_sets))
        lines = [f"✅ 已激活工具集：{', '.join(activated)}（15 分钟内可直接调用）"]
        for ts in activated:
            names = [t.name for t in REGISTRY.list_tools({ts})]
            lines.append(f"- {ts}: {', '.join(names)}")
        lines.append("现在可以直接调用上述工具完成任务。")
        return "\n".join(lines)
    except Exception as e:
        return f"Error finding tools: {e}"
