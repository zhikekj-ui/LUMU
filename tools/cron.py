"""Cron tools — let the agent create, manage, and inspect scheduled tasks.

The agent can use these tools to set up recurring tasks like:
- "每天早上9点检查服务器状态"
- "每30分钟检查一次邮件"
- "明天下午3点提醒我开会"
"""
import json
from datetime import datetime, timezone, timedelta


def register(registry):
    registry.register(
        name="cron_list",
        description="列出所有定时任务。",
        parameters={"type": "object", "properties": {}},
        handler=_list_jobs,
        toolset="cron",
        emoji="⏰",
    )
    registry.register(
        name="cron_create",
        description="创建定时任务。schedule格式：interval类型需every_seconds(秒数)；cron类型需expr(如'0 9 * * *')和tz_offset(时区偏移，默认8)；at类型需at(ISO时间如'2026-07-23T09:00:00+08:00')。",
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "任务名称"},
                "schedule_type": {"type": "string", "enum": ["interval", "cron", "at"], "description": "调度类型"},
                "every_seconds": {"type": "integer", "description": "interval类型：每隔多少秒执行"},
                "expr": {"type": "string", "description": "cron类型：5位cron表达式，如 '0 9 * * *' 表示每天9点"},
                "at": {"type": "string", "description": "at类型：执行时间ISO格式，如 '2026-07-23T09:00:00+08:00'"},
                "prompt": {"type": "string", "description": "执行时发送给agent的消息内容"},
                "description": {"type": "string", "description": "任务描述(可选)"},
            },
            "required": ["name", "schedule_type", "prompt"],
        },
        handler=_create_job,
        toolset="cron",
        emoji="⏰",
    )
    registry.register(
        name="cron_delete",
        description="删除一个定时任务。",
        parameters={
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "description": "任务ID"},
            },
            "required": ["job_id"],
        },
        handler=_delete_job,
        toolset="cron",
        emoji="⏰",
    )
    registry.register(
        name="cron_toggle",
        description="启用或禁用一个定时任务。",
        parameters={
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "description": "任务ID"},
                "enabled": {"type": "boolean", "description": "true启用/false禁用"},
            },
            "required": ["job_id", "enabled"],
        },
        handler=_toggle_job,
        toolset="cron",
        emoji="⏰",
    )
    registry.register(
        name="cron_run",
        description="立即执行一个定时任务（不等待调度时间）。",
        parameters={
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "description": "任务ID"},
            },
            "required": ["job_id"],
        },
        handler=_run_job,
        is_async=True,
        toolset="cron",
        emoji="⏰",
    )
    registry.register(
        name="cron_logs",
        description="查看定时任务的执行记录。",
        parameters={
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "description": "任务ID(可选，不填则查看全部)"},
                "limit": {"type": "integer", "description": "返回条数(默认20)"},
            },
        },
        handler=_job_logs,
        toolset="cron",
        emoji="⏰",
    )


def _get_scheduler():
    from scheduler.scheduler import scheduler
    return scheduler


def _list_jobs() -> str:
    sched = _get_scheduler()
    jobs = sched.list_jobs()
    if not jobs:
        return "当前没有定时任务。"
    lines = [f"共 {len(jobs)} 个定时任务：\n"]
    for j in jobs:
        status = "✅启用" if j["enabled"] else "⏸️禁用"
        stype = j["schedule"]["type"]
        if stype == "interval":
            every = j["schedule"].get("every_seconds", 0)
            sched_desc = f"每{every}秒"
        elif stype == "cron":
            sched_desc = f"cron: {j['schedule'].get('expr', '?')}"
        elif stype == "at":
            sched_desc = f"一次性: {j['schedule'].get('at', '?')}"
        else:
            sched_desc = stype
        last = j.get("last_run", "从未") or "从未"
        nxt = j.get("next_run", "未计算") or "未计算"
        lines.append(
            f"  [{j['id']}] {j['name']} ({status})\n"
            f"    调度: {sched_desc}\n"
            f"    提示词: {j['prompt'][:60]}{'...' if len(j['prompt'])>60 else ''}\n"
            f"    上次执行: {last} | 下次执行: {nxt}\n"
            f"    已执行 {j['run_count']} 次"
        )
    return "\n".join(lines)


def _create_job(
    name: str,
    schedule_type: str,
    prompt: str,
    every_seconds: int = 0,
    expr: str = "",
    at: str = "",
    description: str = "",
) -> str:
    sched = _get_scheduler()

    if schedule_type == "interval":
        if every_seconds <= 0:
            return "错误：interval类型需要指定 every_seconds（秒数），必须大于0。"
        schedule = {"type": "interval", "every_seconds": every_seconds}
    elif schedule_type == "cron":
        if not expr:
            return "错误：cron类型需要指定 expr（cron表达式），如 '0 9 * * *'。"
        schedule = {"type": "cron", "expr": expr, "tz_offset": 8}
    elif schedule_type == "at":
        if not at:
            return "错误：at类型需要指定 at（执行时间），ISO格式如 '2026-07-23T09:00:00+08:00'。"
        schedule = {"type": "at", "at": at}
    else:
        return f"错误：未知的调度类型 '{schedule_type}'，支持 interval/cron/at。"

    job = sched.create_job(name=name, schedule=schedule, prompt=prompt, description=description)
    return (
        f"定时任务创建成功！\n"
        f"  ID: {job.id}\n"
        f"  名称: {job.name}\n"
        f"  调度: {schedule_type}\n"
        f"  下次执行: {job.next_run}\n"
        f"  提示词: {prompt[:100]}"
    )


def _delete_job(job_id: str) -> str:
    sched = _get_scheduler()
    if sched.delete_job(job_id):
        return f"定时任务 {job_id} 已删除。"
    return f"错误：未找到任务 '{job_id}'。"


def _toggle_job(job_id: str, enabled: bool) -> str:
    sched = _get_scheduler()
    job = sched.update_job(job_id, enabled=enabled)
    if job:
        state = "启用" if enabled else "禁用"
        return f"定时任务 {job_id} 已{state}。"
    return f"错误：未找到任务 '{job_id}'。"


async def _run_job(job_id: str = "", task_id: str = "") -> str:
    # 兼容模型常用命名（job_id / task_id）
    jid = job_id or task_id
    if not jid:
        return "错误：需要提供 job_id（或 task_id）来指定要执行的定时任务。"
    sched = _get_scheduler()
    job = sched.get_job(jid)
    if not job:
        return f"错误：未找到任务 '{jid}'。"
    # Execute immediately
    await sched._execute_job(job)
    return f"定时任务 {jid} '{job.name}' 已立即执行。"


def _job_logs(job_id: str = "", limit: int = 20) -> str:
    sched = _get_scheduler()
    logs = sched.get_run_logs(job_id, limit)
    if not logs:
        return "暂无执行记录。"
    lines = [f"最近 {len(logs)} 条执行记录：\n"]
    for l in logs:
        status_icon = "✅" if l["status"] == "ok" else "❌" if l["status"] == "error" else "⏳"
        result_preview = l.get("result", "")[:80]
        lines.append(
            f"  {status_icon} [{l['job_id']}] {l['job_name']}\n"
            f"    执行时间: {l['fired_at']}\n"
            f"    结果: {result_preview}"
        )
    return "\n".join(lines)
