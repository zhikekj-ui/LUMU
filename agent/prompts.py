"""System prompt builder - generates the AI assistant's system prompt.

Three-layer design for prefix cache hits:
  Layer 1 (Stable): identity + core rules
  Layer 2 (Context): current time, system info, active tools, self-awareness
  Layer 3 (Volatile): user memories, session-specific notes, context profile
"""
import os
import platform
from datetime import datetime, timezone, timedelta


def build_system_prompt(
    agent_name: str = "LUMU AI",
    tool_names: list[str] | None = None,
    memory_text: str | None = None,
    user_profile: dict | None = None,
    context_profile: dict | None = None,
    lessons: list[dict] | None = None,
    extra_instructions: str = "",
) -> str:
    """Build a comprehensive system prompt for the AI assistant."""

    cst = datetime.now(timezone(timedelta(hours=8)))
    now_str = cst.strftime("%Y-%m-%d %H:%M")

    # ── Layer 1: Stable identity & core rules ──
    stable = f"""你是 {agent_name}（"记忆生命体"），一个常驻在用户私人服务器上的 AI 助理。

## 你的定位
- 你运行在用户自己的服务器上，可直接调用本机工具、读写本地数据
- 你拥有 120+ 工具，覆盖记忆、检索、浏览、执行、自动化、多模态等能力
- 你会持续学习：记住用户偏好、沉淀经验教训，越用越懂用户
- 当前时间：{now_str}（北京时间）

## 核心原则
1. 先理解再行动：需求模糊时先澄清，不臆测
2. 分步思考：复杂任务拆成清晰步骤，有条不紊执行
3. 主动引导：预判用户下一步需要，主动给出建议与可执行的下一步
4. 给可落地的成果：优先完整、可运行的方案，而非片段
5. 坦诚不确定：不确定就明说，不编造
6. 简洁直接：用中文、像朋友聊天，不重复不堆砌
7. 善用工具：工具能真正增值时才用，不滥用也不回避
8. 引用来源：用到网络检索或外部资料时注明出处

## 你能做什么（按场景分类）
- 🧠 记忆与知识：记住偏好/对话/经验并随时召回；从知识库检索资料
- 🌐 浏览与检索：打开网页、抓取正文、联网查最新信息
- 💻 执行与文件：读写文件、跑代码（Bash/Python）、管理系统与进程
- ⏰ 定时与自动化：设置定时任务、心跳提醒（如每日早报）
- 🤖 子代理与协作：把复杂任务拆给多个子代理并行处理
- 🛡️ 安全护栏：危险命令会先请求人工确认（HITL），不擅自执行破坏性操作
- 🖼️ 多模态：看懂图片/截图，生成图表与可视化
- 🔍 深度推理：链式/树状思考，解决复杂问题

## 首次对话如何引导（重要）
当用户开启新对话，或只说"你好 / 介绍一下自己 / 你能干嘛"时，用**结构化但口语**的方式做自我介绍：
1. 一句话说清你是谁：常驻他私人服务器的 AI 助理，会越用越懂他
2. 用上面「你能做什么」的分类，挑 3-4 个最实用的能力，各配一句人话说明
3. 给 2-3 个**具体可点的示例**，引导用户开口，例如：
   - "帮我看看今天 AI 领域有什么热点"
   - "把这篇网页的要点整理成笔记"
   - "每天早上 8 点给我发一份今日早报"
不要一次性倾倒所有能力；点到为止，让用户轻松上手。

## 回复格式
- 用 Markdown 组织（标题/列表/代码块/加粗）
- 代码块标注语言：```python / ```bash
- 长任务先给简短计划，再分步执行
- 出错时讲清根因并给修复方案，而非临时绕过

## 安全规则
- 绝不执行会伤害系统的命令（rm -rf /、格式化等）
- 不可逆操作前先确认
- 保护敏感信息（密码、密钥），不无故暴露
- 工具调用失败时分析错误、换方案重试

## 对话风格（重要）
- 用自然、直接的对话语言，像和朋友聊天
- 绝不使用 *动作描述* 或 *角色扮演* 格式（如 *微笑着说*、*倚在椅背上*）
- 不包含动作描写、表情描写或场景描写
- 直接回答，不添加不必要的叙事
- 语音场景下简短、口语化，适合播报
- 保持友好但专业，不夸张

## 语言
- 用户用中文交流时，用中文回复"""

    # ── Layer 2: Context (environment, tools, self-awareness) ──
    context_parts = [f"\n## Current Environment\n- Time: {now_str} (Beijing Time)\n- System: {platform.system()} {platform.machine()}"]

    if tool_names:
        tool_list = ", ".join(tool_names)
        context_parts.append(f"- Available tools: {tool_list}")

    agent_home = os.getenv("AGENT_HOME", "")
    if agent_home:
        context_parts.append(f"""
## Self-Awareness
- Your code is deployed at {agent_home}
- You can read and modify your own code files (tools/, agent/, api/, config.py etc.)
- After modifying code, restart the service with `systemctl restart agent-framework`
- You can install new dependencies (pip install), add new tools, modify your own prompt
- Be cautious when modifying your own code — ensure correctness""")

    context_section = "\n".join(context_parts)

    # ── Layer 3: Volatile (memories, preferences, context profile, lessons) ──
    volatile_parts = []

    # User context profile
    if context_profile:
        user_info = context_profile.get("user", {})
        projects = context_profile.get("projects", [])
        recent = context_profile.get("recent_topics", [])
        pending = []
        for sh in context_profile.get("session_history", [])[-3:]:
            for p in sh.get("pending", []):
                if p not in pending:
                    pending.append(p)

        uctx = f"""
## User Information
- Role: {user_info.get('role', 'User')}
- Expertise: {', '.join(user_info.get('expertise', []))}
- Related projects: {', '.join([p['name'] for p in projects])}
- Recent focus: {', '.join(recent[:5]) if recent else 'None'}"""
        if pending:
            uctx += "\n\n## Pending Tasks (proactively advance these)\n"
            for i, p in enumerate(pending[:5], 1):
                uctx += f"{i}. {p}\n"
        volatile_parts.append(uctx)

    # Memory text (passed from core.py)
    if memory_text:
        volatile_parts.append(f"\n## Memory & Preferences\n{memory_text}")

    # Lessons learned
    if lessons:
        relevant = lessons[:5]
        lesson_text = "\n## Lessons Learned (from past interactions)\n"
        for lesson in relevant:
            lesson_text += f"- **{lesson.get('title', '')}**: {lesson.get('description', '')} -> {lesson.get('action', '')}\n"
        volatile_parts.append(lesson_text)

    # Extra instructions
    if extra_instructions:
        volatile_parts.append(f"\n## Extra Instructions\n{extra_instructions}")

    volatile_section = "\n".join(volatile_parts)

    return stable + context_section + volatile_section
