"""System info plugin — provides system diagnostics tools."""
import platform
import shutil
from datetime import datetime

from plugins.base import BasePlugin


class SystemInfoPlugin(BasePlugin):
    name = "system_info"
    version = "1.0.0"
    description = "System diagnostics: disk, uptime, environment info"
    author = "LUMU"

    def register_tools(self, registry):
        registry.register(
            name="system_status",
            description="Get system status: OS, Python version, disk usage, current time.",
            parameters={"type": "object", "properties": {}},
            handler=self._system_status,
            toolset="system",
            emoji="🖥️",
        )

    def _system_status(self) -> str:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        disk = shutil.disk_usage("/")
        disk_gb = disk.free / (1024**3)
        disk_total = disk.total / (1024**3)
        disk_pct = disk.used / disk.total * 100
        return (
            f"System: {platform.system()} {platform.release()} ({platform.machine()})\n"
            f"Python: {platform.python_version()}\n"
            f"Disk: {disk_gb:.1f} GB free / {disk_total:.1f} GB total ({disk_pct:.0f}% used)\n"
            f"Time: {now}"
        )
