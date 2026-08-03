"""Entry point - run the agent framework server."""
import os
import sys

# 确保 AGENT_HOME 兜底为项目根目录：普通用户直接 `python run.py` 不会设该变量，
# 多处模块依赖它做路径解析，必须在入口处设好，避免静默退化。
os.environ.setdefault("AGENT_HOME", os.path.dirname(os.path.abspath(__file__)))

import uvicorn
from config import HOST, PORT
from core.logging_config import configure_logging, get_logger

configure_logging(log_level="INFO", json_format=False)
logger = get_logger("run")

if __name__ == "__main__":
    # macOS 首次运行前置提示：截取桌面依赖屏幕录制授权，提前告知避免失败困惑
    if sys.platform == "darwin":
        logger.info(
            "macOS 提示：使用「截取桌面屏幕」功能前，请到 系统设置 → 隐私与安全性 → 屏幕录制，"
            "授权启动本程序的终端（Terminal/iTerm），并重启该终端后重新运行。否则截图会提示权限不足。"
        )
    elif sys.platform == "win32":
        logger.info(
            "Windows 提示：使用「截取桌面屏幕」功能前，请到 设置 → 隐私和安全性 → 屏幕截图，"
            "打开「允许应用访问你的屏幕」。否则截图可能得到黑屏。"
        )
    logger.info("Starting Agent Framework", host=HOST, port=PORT)
    try:
        from core.access_guard import startup_banner
        startup_banner(HOST, PORT)
    except Exception as _e:
        logger.warning("access_banner_failed", error=str(_e))
    uvicorn.run("api.main:app", host=HOST, port=PORT, reload=False, log_level="info")
