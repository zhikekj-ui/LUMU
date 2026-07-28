#!/usr/bin/env python3
"""幂等 seed：确保「每日晨报」心跳任务存在。

部署后运行一次（或由部署脚本调用）：
    sudo -u lumu HOME=/home/lumu /opt/agent-framework/.venv/bin/python \
        /opt/agent-framework/scripts/setup_heartbeat.py

已存在同名任务则跳过，可安全重复执行。
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scheduler.scheduler import scheduler

MORNING_REPORT_PROMPT = (
    "现在是每日晨报时间。请完成：\n"
    "1) 用 terminal 执行 `date +%Y%m%d` 获取今天日期；\n"
    "2) 用 write_file 把今日晨报写入 data/morning_report_<得到的日期>.md，"
    "内容包括：今日日期与星期、用 terminal 执行 date 确认的服务器时间、一句今日寄语；\n"
    "3) 简短回复确认已生成。"
)


def main():
    for j in scheduler.list_jobs():
        if j.get("name") == "每日晨报":
            print(f"每日晨报任务已存在，跳过: id={j['id']} next={j.get('next_run')}")
            return
    job = scheduler.create_job(
        name="每日晨报",
        schedule={"type": "cron", "expr": "0 8 * * *", "tz_offset": 8},
        prompt=MORNING_REPORT_PROMPT,
        description="每天 08:00 (北京时间) 自动生成当日晨报",
    )
    print(f"已创建每日晨报任务: id={job.id} next_run={job.next_run}")


if __name__ == "__main__":
    main()
