"""Message router — unified entry point for all messaging channels.

Routes incoming messages from any channel to the agent, maintaining
per-chat session isolation so each conversation has its own context.
Supports cross-platform session continuity (对标 OpenClaw/Hermes) when
CROSS_PLATFORM_SESSION is enabled — the same user keeps one conversation
across Telegram / Discord / 企业微信 / 飞书 / 钉钉.
"""
from core.logging_config import get_logger
_logger = get_logger("channels.router")
import uuid
from channels.base import BaseChannel
from channels.telegram import TelegramChannel
from channels.discord_channel import DiscordChannel
from channels.webhook import WebhookChannel
import config


class _ChannelRouter:
    """Manages all channel instances and routes messages to the agent."""

    def __init__(self):
        self._channels: dict[str, BaseChannel] = {}
        self._sessions: dict[str, str] = {}  # session key -> session_id
        self._agent = None

    @staticmethod
    def _session_key(channel_name: str, chat_id: str, user_id: str | None = None,
                     metadata: dict | None = None) -> str:
        """Compute the session key for a message.

        Default (per-channel isolation, group-chat safe):
            key = "{channel}:{chat_id}"
        Cross-platform continuity (CROSS_PLATFORM_SESSION=true):
            the same user shares ONE session across every channel —
            the core of "continue the conversation anywhere".
            Prefer an explicit unified `user_key` from metadata, else user_id.
        """
        if getattr(config, "CROSS_PLATFORM_SESSION", False):
            user_key = (metadata or {}).get("user_key") or user_id
            if user_key:
                return f"user:{user_key}"
        return f"{channel_name}:{chat_id}"

    def _get_or_create_session(self, channel_name: str, chat_id: str,
                               user_id: str | None = None,
                               metadata: dict | None = None) -> str:
        key = self._session_key(channel_name, chat_id, user_id, metadata)
        if key not in self._sessions:
            self._sessions[key] = str(uuid.uuid4())
        return self._sessions[key]

    async def _handle_message(self, channel_name: str, chat_id: str, user_id: str,
                              text: str, metadata: dict | None = None) -> str:
        """Route an incoming message to the agent and return the reply."""
        if not self._agent:
            return "Agent not initialized"

        session_id = self._get_or_create_session(channel_name, chat_id, user_id, metadata)

        # Handle special commands
        if text.strip().lower() in ("/new", "/reset"):
            self._agent.clear_session(session_id)
            key = self._session_key(channel_name, chat_id, user_id, metadata)
            self._sessions.pop(key, None)
            return "会话已重置。"

        try:
            result = await self._agent.chat(text, session_id)
            return result.get("content", "抱歉，处理消息时出错了。")
        except Exception as e:
            _logger.info(f"[router] Error handling message from {channel_name}/{chat_id}: {e}")
            return f"处理出错: {e}"

    def get_channel(self, name: str) -> BaseChannel | None:
        """Get a started channel by name (used by the callback route)."""
        return self._channels.get(name)

    # ---- channel factories (config-driven, lazy import) ----
    def _make_wecom(self):
        if not (config.WECHAT_WORK_CORP_ID and config.WECHAT_WORK_SECRET and config.WECHAT_WORK_AGENT_ID):
            return None
        from channels.wecom import WeComChannel
        return WeComChannel(
            corp_id=config.WECHAT_WORK_CORP_ID,
            agent_id=config.WECHAT_WORK_AGENT_ID,
            secret=config.WECHAT_WORK_SECRET,
            token=config.WECHAT_WORK_TOKEN,
            aes_key=config.WECHAT_WORK_AES_KEY,
        )

    def _make_feishu(self):
        if not (config.FEISHU_APP_ID and config.FEISHU_APP_SECRET):
            return None
        from channels.feishu import FeishuChannel
        return FeishuChannel(
            app_id=config.FEISHU_APP_ID,
            app_secret=config.FEISHU_APP_SECRET,
            verify_token=config.FEISHU_VERIFY_TOKEN,
            encrypt_key=config.FEISHU_ENCRYPT_KEY,
        )

    def _make_dingtalk(self):
        if not (config.DINGTALK_APP_KEY and config.DINGTALK_APP_SECRET):
            return None
        from channels.dingtalk import DingTalkChannel
        return DingTalkChannel(
            app_key=config.DINGTALK_APP_KEY,
            app_secret=config.DINGTALK_APP_SECRET,
            agent_id=config.DINGTALK_AGENT_ID,
            token=config.DINGTALK_TOKEN,
            aes_key=config.DINGTALK_AES_KEY,
        )

    async def _try_start(self, name: str, factory):
        try:
            ch = factory()
            if ch is None:
                return
            ch.set_message_handler(self._handle_message)
            self._channels[name] = ch
            await ch.start()
            _logger.info(f"[channels] {name} started")
        except Exception as e:
            _logger.info(f"[channels] {name} failed: {e}")

    async def start_all(self, agent):
        """Initialize and start all configured channels."""
        self._agent = agent

        # Telegram
        if config.TELEGRAM_BOT_TOKEN:
            await self._try_start("telegram", lambda: TelegramChannel(config.TELEGRAM_BOT_TOKEN))

        # Discord
        if config.DISCORD_BOT_TOKEN:
            await self._try_start("discord", lambda: DiscordChannel(config.DISCORD_BOT_TOKEN))

        # Webhook (always available, no external token needed)
        await self._try_start("webhook", lambda: WebhookChannel())

        # 国内渠道（主战场）：企业微信 / 飞书 / 钉钉
        await self._try_start("wecom", self._make_wecom)
        await self._try_start("feishu", self._make_feishu)
        await self._try_start("dingtalk", self._make_dingtalk)

        _logger.info(f"[channels] active: {list(self._channels.keys())}")

    async def stop_all(self):
        """Stop all running channels."""
        for name, ch in self._channels.items():
            try:
                await ch.stop()
                _logger.info(f"[channels] {name} stopped")
            except Exception as e:
                _logger.info(f"[channels] Error stopping {name}: {e}")
        self._channels.clear()

    async def route(self, channel_name: str, chat_id: str, user_id: str, text: str, metadata: dict) -> str:
        """Route a message from a specific channel (used by webhook endpoint)."""
        ch = self._channels.get(channel_name)
        handler = ch._on_message if ch else None
        if not handler:
            # Use the generic handler
            handler = self._handle_message
        return await handler(channel_name, chat_id, user_id, text, metadata)

    def get_status(self) -> list[dict]:
        """Get status of all channels."""
        return [ch.get_status() for ch in self._channels.values()]


# Singleton
channel_router = _ChannelRouter()
