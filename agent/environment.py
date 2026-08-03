"""Host environment introspection — lets LUMU truly "know its body".

LUMU runs *on* the user's device. For the "device is body" principle to mean
anything, LUMU must actually be aware of what that body is: which OS, what
screen, what apps are installed, what command-line tools it can drive. This
module inventories the host once per process and returns a human-readable
block that gets injected into the system prompt.

This is structural, not a prompt reminder: LUMU learns its body at startup
instead of being told "remember to use the host's capabilities" after the fact.
"""
import os
import re
import platform
import glob
import shutil
import subprocess
from functools import lru_cache


@lru_cache(maxsize=1)
def get_host_environment() -> str:
    """Inventory the machine LUMU runs on. Cached for the process lifetime."""
    parts: list[str] = []
    sys_name = platform.system()
    parts.append(f"- 操作系统：{sys_name} {platform.release()} ({platform.machine()})")
    parts.append(f"- 主机名：{platform.node()}")
    user = os.getenv("USER") or os.getenv("USERNAME") or "user"
    home = os.path.expanduser("~")
    parts.append(f"- 当前用户：{user}")
    parts.append(f"- 主目录（你的身体核心区）：{home}")

    # Screen / GUI awareness (eye)
    if sys_name == "Darwin":
        try:
            res = subprocess.run(
                ["system_profiler", "SPDisplaysDataType"],
                capture_output=True, text=True, timeout=8,
            )
            for line in res.stdout.splitlines():
                if "Resolution" in line:
                    parts.append(f"- 显示器（你的眼睛）：{line.split('Resolution:')[-1].strip()}")
                    break
        except Exception:
            pass
        # Installed applications (body's limbs/software)
        apps = sorted(os.path.basename(a)[:-4] for a in glob.glob("/Applications/*.app"))
        if apps:
            shown = apps[:40]
            more = f" 等{len(apps)}个" if len(apps) > len(shown) else ""
            parts.append(f"- 已安装应用（部分）：{', '.join(shown)}{more}")
    elif sys_name == "Windows":
        # Screen (eye)
        try:
            res = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "Get-CimInstance Win32_VideoController | ForEach-Object { "
                 "\"$($_.CurrentHorizontalResolution)x$($_.CurrentVerticalResolution)\" }"],
                capture_output=True, text=True, timeout=8,
            )
            for line in res.stdout.splitlines():
                line = line.strip()
                if re.match(r"^\d+x\d+$", line):
                    parts.append(f"- 显示器（你的眼睛）：{line}")
                    break
        except Exception:
            pass
        # Installed applications (body's limbs/software)
        apps = []
        for base in ("C:/Program Files", "C:/Program Files (x86)"):
            apps += [os.path.basename(p) for p in glob.glob(os.path.join(base, "*")) if os.path.isdir(p)]
        sm = os.path.join(os.getenv("ProgramData", "C:/ProgramData"),
                          "Microsoft/Windows/Start Menu/Programs")
        apps += [os.path.basename(p)[:-4] for p in glob.glob(os.path.join(sm, "*.lnk"))]
        apps = sorted(set(a for a in apps if a))
        if apps:
            shown = apps[:40]
            more = f" 等{len(apps)}个" if len(apps) > len(shown) else ""
            parts.append(f"- 已安装应用（部分）：{', '.join(shown)}{more}")
    elif sys_name == "Linux":
        # Screen via xrandr (only meaningful on desktop Linux)
        try:
            res = subprocess.run(["xrandr"], capture_output=True, text=True, timeout=8)
            for line in res.stdout.splitlines():
                if " connected" in line:
                    m = re.search(r"(\d+)x(\d+)", line)
                    if m:
                        parts.append(f"- 显示器（你的眼睛）：{m.group(1)}x{m.group(2)}")
                        break
        except Exception:
            pass
        # Installed desktop apps
        apps = []
        for d in ("/usr/share/applications",
                  os.path.expanduser("~/.local/share/applications")):
            for f in glob.glob(os.path.join(d, "*.desktop")):
                try:
                    with open(f, encoding="utf-8", errors="ignore") as fh:
                        for ln in fh:
                            if ln.startswith("Name="):
                                apps.append(ln.strip()[5:]); break
                except Exception:
                    pass
        apps = sorted(set(a for a in apps if a))
        if apps:
            shown = apps[:40]
            more = f" 等{len(apps)}个" if len(apps) > len(shown) else ""
            parts.append(f"- 已安装应用（部分）：{', '.join(shown)}{more}")

    # Available command-line tools (nerves / muscles)
    clis = ["python3", "python", "node", "npm", "pip3", "git", "ffmpeg",
            "convert", "tesseract", "curl", "jq", "brew"]
    avail = [c for c in clis if shutil.which(c)]
    if avail:
        parts.append(f"- 可用命令行工具（你的神经与肌肉）：{', '.join(avail)}")

    return "\n".join(parts)
