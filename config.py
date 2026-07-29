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
from dataclasses import dataclass, field
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
# 跨平台默认工作目录：Windows / macOS / Linux 三端通用（~/lumu-workspace）。
# 仅当环境变量 AGENT_BASE_DIR 完全未设置时生效；设为空字符串时回落到 cwd（与 .env 现状兼容）。
AGENT_BASE_DIR = os.getenv('AGENT_BASE_DIR', os.path.expanduser('~/lumu-workspace'))
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

# ── 国内渠道（主战场）配置预留 ──
# 对标 OpenClaw 多频道网关的国内版：企业微信 / 飞书 / 钉钉。
# 各平台「填齐必填项即激活」，缺任一必填项则该渠道不启动（不影响其他渠道）。
# 回调式平台需把回调 URL 配到对应后台：
#   https://<你的域名或IP>:8000/api/channels/{wecom|feishu|dingtalk}/callback
# 该 URL 需公网可达 + HTTPS（建议 Nginx 反代终止 TLS）。
# 跨平台会话延续（默认关；开启后同一用户在任意渠道共享上下文，对标 OpenClaw/Hermes）：
CROSS_PLATFORM_SESSION = os.getenv('CROSS_PLATFORM_SESSION', 'false').lower() == 'true'

# 企业微信（自建应用）：corpid + secret + agentid 必填；token/aes_key 为回调校验
WECHAT_WORK_CORP_ID = os.getenv('WECHAT_WORK_CORP_ID', '')
WECHAT_WORK_AGENT_ID = os.getenv('WECHAT_WORK_AGENT_ID', '')
WECHAT_WORK_SECRET = os.getenv('WECHAT_WORK_SECRET', '')
WECHAT_WORK_TOKEN = os.getenv('WECHAT_WORK_TOKEN', '')
WECHAT_WORK_AES_KEY = os.getenv('WECHAT_WORK_AES_KEY', '')   # 明文模式留空

# 飞书（企业自建应用）
FEISHU_APP_ID = os.getenv('FEISHU_APP_ID', '')
FEISHU_APP_SECRET = os.getenv('FEISHU_APP_SECRET', '')
FEISHU_VERIFY_TOKEN = os.getenv('FEISHU_VERIFY_TOKEN', '')
FEISHU_ENCRYPT_KEY = os.getenv('FEISHU_ENCRYPT_KEY', '')

# 钉钉（企业内部应用）
DINGTALK_APP_KEY = os.getenv('DINGTALK_APP_KEY', '')
DINGTALK_APP_SECRET = os.getenv('DINGTALK_APP_SECRET', '')
DINGTALK_AGENT_ID = os.getenv('DINGTALK_AGENT_ID', '')
DINGTALK_TOKEN = os.getenv('DINGTALK_TOKEN', '')
DINGTALK_AES_KEY = os.getenv('DINGTALK_AES_KEY', '')

# ── 媒体生成（图像/视频）配置接口预留 ──
# 图像/视频生成属于「模型能力」：框架只统一预留各家厂商的配置接口，
# 实际生成管线后续按 MEDIA_PROVIDER + get_media_config() 接入。
# 任一厂商未配置密钥时整体降级为不可用，不影响主对话。
@dataclass
class MediaGenProvider:
    """声明式厂商规格（与 LLM 的 ProviderProfile 同风格，但面向图像/视频）。"""
    name: str
    display_name: str
    api_key_env: str
    base_url: str = ""
    image_model: str = ""
    video_model: str = ""
    _api_key: str = field(default="", repr=False)  # 运行时由 env 解析，仅占位

    def resolve_api_key(self) -> str:
        return os.getenv(self.api_key_env, "")

    def is_configured(self) -> bool:
        return bool(self.resolve_api_key())

    def as_dict(self) -> dict:
        # 支持 {NAME}_IMAGE_MODEL / {NAME}_VIDEO_MODEL / {NAME}_BASE_URL 覆盖默认
        up = self.name.upper()
        return {
            "name": self.name,
            "display_name": self.display_name,
            "api_key": self.resolve_api_key(),
            "base_url": os.getenv(f"{up}_BASE_URL", self.base_url),
            "image_model": os.getenv(f"{up}_IMAGE_MODEL", self.image_model),
            "video_model": os.getenv(f"{up}_VIDEO_MODEL", self.video_model),
        }


# 默认媒体厂商：none | openai | dashscope | zhipu | stability | flux | kling | seedance
MEDIA_PROVIDER = os.getenv("MEDIA_PROVIDER", "none").lower()

# 各厂商配置接口（密钥留空即该厂商不可用；openai 复用 OPENAI_API_KEY）
MEDIA_PROVIDERS: dict[str, MediaGenProvider] = {
    "openai": MediaGenProvider(
        name="openai", display_name="OpenAI (DALL·E / gpt-image / Sora)",
        api_key_env="OPENAI_API_KEY", base_url="https://api.openai.com/v1",
        image_model="gpt-image-1", video_model="sora-2",
    ),
    "dashscope": MediaGenProvider(
        name="dashscope", display_name="阿里通义万相 (DashScope)",
        api_key_env="DASHSCOPE_API_KEY", base_url="https://dashscope.aliyuncs.com/api/v1",
        image_model="wanx2.1-t2i-turbo", video_model="wanx2.1-i2v-turbo",
    ),
    "zhipu": MediaGenProvider(
        name="zhipu", display_name="智谱 CogView / CogVideo",
        api_key_env="ZHIPU_API_KEY", base_url="https://open.bigmodel.cn/api/paas/v4",
        image_model="cogview-3-plus", video_model="cogvideox-2",
    ),
    "stability": MediaGenProvider(
        name="stability", display_name="Stability AI",
        api_key_env="STABILITY_API_KEY", base_url="https://api.stability.ai/v2",
        image_model="stable-diffusion-3.5-large",
    ),
    "flux": MediaGenProvider(
        name="flux", display_name="FLUX (Black Forest Labs)",
        api_key_env="FLUX_API_KEY", base_url="https://api.bfl.ai",
        image_model="FLUX.1.1 [pro]",
    ),
    "kling": MediaGenProvider(
        name="kling", display_name="可灵 (Kling)",
        api_key_env="KLING_API_KEY", base_url="https://api.klingai.com",
        video_model="kling-v2-master",
    ),
    "seedance": MediaGenProvider(
        name="seedance", display_name="字节 Seedance / 即梦",
        api_key_env="SEEDANCE_API_KEY", base_url="https://api.seedance.ai",
        video_model="seedance-v1-pro",
    ),
}


def get_media_config(provider: str | None = None) -> dict:
    """预留访问器：按厂商名返回图像/视频生成配置。
    未配置密钥（或厂商不存在）返回空 dict，调用方据此判定「不可用」，优雅降级。"""
    p = (provider or MEDIA_PROVIDER).lower()
    spec = MEDIA_PROVIDERS.get(p)
    if spec is None or not spec.is_configured():
        return {}
    return spec.as_dict()


LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
JSON_LOGS = os.getenv("JSON_LOGS", "false").lower() == "true"
