"""DateTime tool — gives the agent awareness of time."""
from datetime import datetime, timezone


def register(registry):
    registry.register(
        name="get_current_time",
        description="Get current date and time (UTC and Asia/Shanghai).",
        parameters={
            "type": "object",
            "properties": {},
        },
        handler=get_time,
        toolset="system",
        emoji="🕐",
    )


def get_time() -> str:
    utc = datetime.now(timezone.utc)
    # Asia/Shanghai = UTC+8
    from datetime import timedelta
    cst = utc + timedelta(hours=8)
    return (
        f"UTC: {utc.strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"Asia/Shanghai: {cst.strftime('%Y-%m-%d %H:%M:%S')}"
    )
