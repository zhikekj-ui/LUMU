"""Webhook channel — generic HTTP webhook adapter.

Messages arrive via POST /api/webhook/{channel_name} in api/main.py.
This channel is always available and doesn't require external tokens.
It's the universal integration point for custom systems
(企业微信, 飞书, Slack incoming webhooks, etc.).
"""
from channels.base import BaseChannel


class WebhookChannel(BaseChannel):
    """Generic webhook channel — receives messages via HTTP POST."""

    name = "webhook"

    def __init__(self):
        super().__init__()
        self.enabled = True

    async def start(self):
        # Webhook is always ready — routes are handled by FastAPI
        self.enabled = True

    async def stop(self):
        self.enabled = False

    async def send_message(self, chat_id: str, text: str, reply_to: str | None = None):
        # Webhook replies are returned directly in the HTTP response
        # No push mechanism — the caller receives the reply synchronously
        pass

    def get_status(self) -> dict:
        return {
            "name": self.name,
            "enabled": self.enabled,
            "platform": "webhook",
            "endpoint": "/api/webhook/webhook",
        }
