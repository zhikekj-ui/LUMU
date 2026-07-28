"""Configuration management."""
# === SQLite 健壮性补丁（Phase B 稳定性加固，2026-07-28）===
# 根因：服务所有 SQLite 读写都跑在 async 事件循环里，原连接未设锁超时，
# 一旦遇锁竞争（并发写 / 遗留进程持锁）会无限阻塞事件循环，拖垮整个服务
# （曾致全服务不可用）。补丁统一给所有 sqlite3.connect 加 timeout + busy_timeout，
# 锁等待有上限、到点 fail-fast，单个请求失败而不会瘫痪全局。
import sqlite3 as _sqlite3
_orig_connect = _sqlite3.connect
def _patched_sqlite_connect(*args, **kwargs):
    kwargs.setdefault("timeout", 5.0)
    _conn = _orig_connect(*args, **kwargs)
    try:
        _conn.execute("PRAGMA busy_timeout=5000")
    except Exception:
        pass
    return _conn
_sqlite3.connect = _patched_sqlite_connect
# ===========================================================
import os
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / 'data'
SKILLS_DIR = BASE_DIR / 'skills'
PLUGINS_DIR = BASE_DIR / 'plugins'
DATA_DIR.mkdir(exist_ok=True)
DEFAULT_PROVIDER = os.getenv('DEFAULT_PROVIDER', 'openai')
DEFAULT_MODEL = os.getenv('DEFAULT_MODEL', 'gpt-4o-mini')
VISION_MODEL = os.getenv('VISION_MODEL', 'step-1.5v-mini')
VISION_FALLBACK = os.getenv('VISION_FALLBACK', 'step-1v-8k')
CONTEXT_WINDOW = int(os.getenv('CONTEXT_WINDOW', '128000'))
COMPRESS_THRESHOLD = float(os.getenv('COMPRESS_THRESHOLD', '0.75'))
HOST = os.getenv('HOST', '0.0.0.0')
PORT = int(os.getenv('PORT', '8000'))
API_KEY = os.getenv('API_KEY', '')
AGENT_BASE_DIR = os.getenv('AGENT_BASE_DIR', '/root')
AGENT_HOME = os.getenv('AGENT_HOME', str(BASE_DIR))
EMBEDDING_DIM = int(os.getenv('EMBEDDING_DIM', '512'))
SEMANTIC_SIMILARITY_THRESHOLD = float(os.getenv('SEMANTIC_SIMILARITY_THRESHOLD', '0.15'))
LEARNING_ENABLED = os.getenv('LEARNING_ENABLED', 'true').lower() == 'true'
# 经验提炼阈值：分数 >= 高阈值（表现极好）或 <= 低阈值（表现极差）的交互才值得提炼为教训。
# 注意：这是两个独立的边界，不是区间；切勿写成 MIN <= score <= MAX。
LESSON_EXTRACTION_HIGH_SCORE = int(os.getenv('LESSON_EXTRACTION_HIGH_SCORE', '7'))
LESSON_EXTRACTION_LOW_SCORE = int(os.getenv('LESSON_EXTRACTION_LOW_SCORE', '4'))
MCP_SERVERS = os.getenv('MCP_SERVERS', '')
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '')
DISCORD_BOT_TOKEN = os.getenv('DISCORD_BOT_TOKEN', '')
WEBHOOK_SECRET = os.getenv('WEBHOOK_SECRET', '')

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
JSON_LOGS = os.getenv("JSON_LOGS", "false").lower() == "true"
