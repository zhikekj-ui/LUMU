"""Admin operations API - system info, backup, monitoring."""
import os
import platform
import subprocess
import shutil
import psutil
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Depends
from auth.deps import get_admin_user
from models.user import User

router = APIRouter(prefix="/api/admin", tags=["admin"])

@router.get("/system-info")
async def get_system_info(admin: User = Depends(get_admin_user)):
    disk = shutil.disk_usage(os.path.abspath(os.sep))
    mem = psutil.virtual_memory()
    return {
        "hostname": platform.node(),
        "os": f"{platform.system()} {platform.release()}",
        "cpu_count": psutil.cpu_count(),
        "cpu_percent": psutil.cpu_percent(interval=0.5),
        "memory": {
            "total_gb": round(mem.total / (1024**3), 2),
            "used_gb": round(mem.used / (1024**3), 2),
            "available_gb": round(mem.available / (1024**3), 2),
            "percent": mem.percent,
        },
        "disk": {
            "total_gb": round(disk.total / (1024**3), 2),
            "used_gb": round(disk.used / (1024**3), 2),
            "free_gb": round(disk.free / (1024**3), 2),
            "percent": round((disk.used / disk.total) * 100, 1),
        },
        "uptime_hours": round(psutil.boot_time() / 3600, 1),
    }

@router.get("/stats")
async def get_usage_stats(admin: User = Depends(get_admin_user)):
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy import text
    import os

    engine = create_async_engine(os.getenv("DATABASE_URL", "postgresql+asyncpg://lumu:LumuSecure2026!@localhost:5432/lumu_agent"))
    async with engine.connect() as conn:
        user_count = (await conn.execute(text("SELECT COUNT(*) FROM users"))).scalar()
        session_count = (await conn.execute(text("SELECT COUNT(*) FROM usage_records"))).scalar()
        total_tokens = (await conn.execute(text("SELECT COALESCE(SUM(tokens_total), 0) FROM usage_records"))).scalar()
    await engine.dispose()

    return {
        "total_users": user_count,
        "total_requests": session_count,
        "total_tokens": total_tokens,
    }

@router.post("/backup")
async def trigger_backup(admin: User = Depends(get_admin_user)):
    _home = os.getenv("AGENT_HOME", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    result = subprocess.run(
        [os.path.join(_home, "scripts", "backup.sh")],
        capture_output=True, text=True, timeout=300
    )
    if result.returncode == 0:
        return {"status": "ok", "output": result.stdout}
    raise HTTPException(500, detail=result.stderr)
