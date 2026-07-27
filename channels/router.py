"""Message router — unified entry point for all messaging channels.

Routes incoming messages from any channel to the agent, maintaining
per-chat session isolation so each conversation has its own context.
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
        self._sessions: dict[str, str] = {}  # (channel, chat_id) → session_id
        self._agent = None

    def _get_or_create_session(self, channel_name: str, chat_id: str) -> str:
        """Get or create a session ID for a (channel, chat_id) pair."""
        key = f"{channel_name}:{chat_id}"
        if key not in self._sessions:
            self._sessions[key] = str(uuid.uuid4())
        return self._sessions[key]

    async def _handle_message(self, channel_name: str, chat_id: str, user_id: str, text: str, metadata: dict) -> str:
        """Route an incoming message to the agent and return the reply."""
        if not self._agent:
            return "Agent not initialized"

        session_id = self._get_or_create_session(channel_name, chat_id)

        # Handle special commands
        if text.strip().lower() in ("/new", "/reset"):
            self._agent.clear_session(session_id)
            del self._sessions[f"{channel_name}:{chat_id}"]
            return "会话已重置。"

        try:
            result = await self._agent.chat(text, session_id)
            return result.get("content", "抱歉，处理消息时出错了。")
        except Exception as e:
            _logger.info(f"[router] Error handling message from {channel_name}/{chat_id}: {e}")
            return f"处理出错: {e}"

    async def start_all(self, agent):
        """Initialize and start all configured channels."""
        self._agent = agent

        # Telegram
        if config.TELEGRAM_BOT_TOKEN:
            ch = TelegramChannel(config.TELEGRAM_BOT_TOKEN)
            ch.set_message_handler(self._handle_message)
            self._channels["telegram"] = ch
            try:
                await ch.start()
                _logger.info(f"[channels] Telegram started")
            except Exception as e:
                _logger.info(f"[channels] Telegram failed: {e}")

        # Discord
        if config.DISCORD_BOT_TOKEN:
            ch = DiscordChannel(config.DISCORD_BOT_TOKEN)
            ch.set_message_handler(self._handle_message)
            self._channels["discord"] = ch
            try:
                await ch.start()
                _logger.info(f"[channels] Discord started")
            except Exception as e:
                _logger.info(f"[channels] Discord failed: {e}")

        # Webhook (always available, no external token needed)
        ch = WebhookChannel()
        ch.set_message_handler(self._handle_message)
        self._channels["webhook"] = ch
        ch.enabled = True
        _logger.info(f"[channels] Webhook ready")

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
        handler = None
        if channel_name in self._channels:
            handler = self._channels[channel_name]._on_message
        if not handler:
            # Use the generic handler
            handler = self._handle_message
        return await handler(channel_name, chat_id, user_id, text, metadata)

    def get_status(self) -> list[dict]:
        """Get status of all channels."""
        return [ch.get_status() for ch in self._channels.values()]


# Singleton
channel_router = _ChannelRouter()
