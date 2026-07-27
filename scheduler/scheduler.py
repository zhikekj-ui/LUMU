"""Scheduler — background task scheduler for the agent framework.

Supports three schedule types:
- interval: every N seconds/minutes
- cron: standard 5-field cron expression
- at: one-shot at a specific ISO-8601 time

When a job fires, its prompt is sent to the agent as a new message.
Results are stored for auditing.
"""
import asyncio
import json
import uuid
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger("scheduler")

DATA_FILE = Path(__file__).parent.parent / "data" / "cron_jobs.json"
RUN_LOG_FILE = Path(__file__).parent.parent / "data" / "cron_runs.json"
MAX_RUN_LOGS = 200


@dataclass
class CronJob:
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = ""
    description: str = ""
    # Schedule: {"type": "interval"|"cron"|"at", ...}
    # interval: {"type": "interval", "every_seconds": 300}
    # cron: {"type": "cron", "expr": "0 9 * * *", "tz": "Asia/Shanghai"}
    # at: {"type": "at", "at": "2026-07-23T09:00:00+08:00"}
    schedule: dict = field(default_factory=dict)
    prompt: str = ""           # Message to send to agent
    enabled: bool = True
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    last_run: str = ""
    next_run: str = ""
    run_count: int = 0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "CronJob":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


def _parse_cron_field(expr: str, min_val: int, max_val: int) -> list[int]:
    """Parse a single cron field into a list of valid values."""
    values = set()
    for part in expr.split(","):
        part = part.strip()
        if "/" in part:
            range_part, step = part.split("/", 1)
            step = int(step)
            if range_part == "*":
                start, end = min_val, max_val
            elif "-" in range_part:
                start, end = map(int, range_part.split("-", 1))
            else:
                start, end = int(range_part), max_val
            values.update(range(start, end + 1, step))
        elif part == "*":
            values.update(range(min_val, max_val + 1))
        elif "-" in part:
            start, end = map(int, part.split("-", 1))
            values.update(range(start, end + 1))
        else:
            values.add(int(part))
    return sorted(values)


def _next_cron_time(expr: str, tz_offset_hours: float = 8) -> datetime:
    """Calculate next fire time for a 5-field cron expression.
    
    Fields: minute hour day_of_month month day_of_week
    Returns UTC datetime.
    """
    parts = expr.strip().split()
    if len(parts) != 5:
        raise ValueError(f"Invalid cron expression: {expr}")
    
    minutes = _parse_cron_field(parts[0], 0, 59)
    hours = _parse_cron_field(parts[1], 0, 23)
    doms = _parse_cron_field(parts[2], 1, 31)
    months = _parse_cron_field(parts[3], 1, 12)
    dows = _parse_cron_field(parts[4], 0, 6)  # 0=Monday

    tz = timezone(timedelta(hours=tz_offset_hours))
    now = datetime.now(tz)
    # Start checking from next minute
    candidate = now.replace(second=0, microsecond=0) + timedelta(minutes=1)

    # Search up to 366 days ahead
    for _ in range(366 * 24 * 60):
        if (candidate.month in months and
            candidate.day in doms and
            candidate.hour in hours and
            candidate.minute in minutes and
            candidate.weekday() in dows):
            return candidate.astimezone(timezone.utc)
        candidate += timedelta(minutes=1)

    raise ValueError("Could not find next cron fire time within 366 days")


def _compute_next_run(schedule: dict) -> str:
    """Compute next run time as ISO string."""
    stype = schedule.get("type", "")
    now = datetime.now(timezone.utc)

    if stype == "interval":
        every = schedule.get("every_seconds", 300)
        next_time = now + timedelta(seconds=every)
        return next_time.isoformat()

    elif stype == "cron":
        expr = schedule.get("expr", "0 * * * *")
        tz_hours = schedule.get("tz_offset", 8)
        try:
            return _next_cron_time(expr, tz_hours).isoformat()
        except ValueError:
            return ""

    elif stype == "at":
        at_str = schedule.get("at", "")
        if at_str:
            return at_str  # Already an ISO string
        return ""

    return ""


class Scheduler:
    """Background scheduler that fires cron jobs and sends prompts to the agent."""

    def __init__(self):
        self._jobs: dict[str, CronJob] = {}
        self._run_logs: list[dict] = []
        self._task: asyncio.Task | None = None
        self._running = False
        self._agent_ref = None  # Weak reference to agent
        self._load_jobs()
        self._load_run_logs()

    def set_agent(self, agent):
        """Set the agent reference for executing job prompts."""
        self._agent_ref = agent

    def _load_jobs(self):
        if DATA_FILE.exists():
            try:
                data = json.loads(DATA_FILE.read_text())
                for d in data:
                    job = CronJob.from_dict(d)
                    self._jobs[job.id] = job
            except Exception as e:
                logger.error(f"Failed to load cron jobs: {e}")

    def _save_jobs(self):
        DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
        data = [j.to_dict() for j in self._jobs.values()]
        DATA_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2))

    def _load_run_logs(self):
        if RUN_LOG_FILE.exists():
            try:
                self._run_logs = json.loads(RUN_LOG_FILE.read_text())
            except Exception:
                self._run_logs = []

    def _save_run_logs(self):
        RUN_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        # Keep only recent logs
        if len(self._run_logs) > MAX_RUN_LOGS:
            self._run_logs = self._run_logs[-MAX_RUN_LOGS:]
        RUN_LOG_FILE.write_text(json.dumps(self._run_logs, ensure_ascii=False, indent=2))

    # --- CRUD ---
    def create_job(self, name: str, schedule: dict, prompt: str, description: str = "") -> CronJob:
        job = CronJob(
            name=name,
            description=description,
            schedule=schedule,
            prompt=prompt,
        )
        job.next_run = _compute_next_run(schedule)
        self._jobs[job.id] = job
        self._save_jobs()
        logger.info(f"Created cron job: {job.id} '{name}' next={job.next_run}")
        return job

    def update_job(self, job_id: str, **kwargs) -> CronJob | None:
        job = self._jobs.get(job_id)
        if not job:
            return None
        for k, v in kwargs.items():
            if hasattr(job, k) and k != "id":
                setattr(job, k, v)
        if "schedule" in kwargs:
            job.next_run = _compute_next_run(job.schedule)
        self._save_jobs()
        return job

    def delete_job(self, job_id: str) -> bool:
        if job_id in self._jobs:
            del self._jobs[job_id]
            self._save_jobs()
            return True
        return False

    def list_jobs(self) -> list[dict]:
        return [j.to_dict() for j in self._jobs.values()]

    def get_job(self, job_id: str) -> CronJob | None:
        return self._jobs.get(job_id)

    def get_run_logs(self, job_id: str = "", limit: int = 20) -> list[dict]:
        logs = self._run_logs
        if job_id:
            logs = [l for l in logs if l.get("job_id") == job_id]
        return logs[-limit:]

    # --- Execution ---
    async def _execute_job(self, job: CronJob):
        """Execute a cron job by sending its prompt to the agent."""
        if not self._agent_ref:
            logger.warning(f"No agent reference, cannot execute job {job.id}")
            return

        job.last_run = datetime.now(timezone.utc).isoformat()
        job.run_count += 1
        job.next_run = _compute_next_run(job.schedule)
        self._save_jobs()

        log_entry = {
            "job_id": job.id,
            "job_name": job.name,
            "prompt": job.prompt,
            "fired_at": job.last_run,
            "status": "running",
            "result": "",
        }

        try:
            # Send prompt to agent (non-streaming for background execution)
            result = await self._agent_ref.chat(job.prompt)
            log_entry["status"] = "ok"
            log_entry["result"] = result.get("content", "")[:2000]
            logger.info(f"Cron job {job.id} '{job.name}' executed OK")
        except Exception as e:
            log_entry["status"] = "error"
            log_entry["result"] = str(e)
            logger.error(f"Cron job {job.id} '{job.name}' failed: {e}")

        self._run_logs.append(log_entry)
        self._save_run_logs()

    async def _loop(self):
        """Main scheduler loop — checks every 10 seconds for due jobs."""
        logger.info("Scheduler loop started")
        while self._running:
            try:
                now = datetime.now(timezone.utc)
                for job in list(self._jobs.values()):
                    if not job.enabled:
                        continue
                    if not job.next_run:
                        job.next_run = _compute_next_run(job.schedule)
                        self._save_jobs()
                        continue
                    try:
                        next_dt = datetime.fromisoformat(job.next_run)
                        if next_dt.tzinfo is None:
                            next_dt = next_dt.replace(tzinfo=timezone.utc)
                    except (ValueError, TypeError):
                        continue

                    if now >= next_dt:
                        logger.info(f"Firing cron job: {job.id} '{job.name}'")
                        asyncio.create_task(self._execute_job(job))

                await asyncio.sleep(10)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Scheduler loop error: {e}")
                await asyncio.sleep(10)

    async def start(self):
        """Start the scheduler background task."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info(f"Scheduler started with {len(self._jobs)} jobs")

    async def stop(self):
        """Stop the scheduler."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Scheduler stopped")


# Global scheduler instance
scheduler = Scheduler()
