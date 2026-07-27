"""Base channel adapter — abstract interface for all messaging channels."""
from abc import ABC, abstractmethod
from typing import Callable, Awaitable


class BaseChannel(ABC):
    """Abstract base for messaging channel adapters.

    Each channel bridges an external messaging platform (Telegram, Discord, etc.)
    to the agent framework. Subclasses implement platform-specific send/receive
    logic while the router handles session management and agent dispatch.
    """

    name: str = "unknown"
    enabled: bool = False

    def __init__(self):
        self._on_message: Callable[[str, str, str, dict], Awaitable[str]] | None = None

    @abstractmethod
    async def start(self):
        """Start listening for messages."""
        ...

    @abstractmethod
    async def stop(self):
        """Stop listening and clean up resources."""
        ...

    @abstractmethod
    async def send_message(self, chat_id: str, text: str, reply_to: str | None = None):
        """Send a message to a specific chat/conversation."""
        ...

    def set_message_handler(self, handler: Callable[[str, str, str, dict], Awaitable[str]]):
        """Set the callback for incoming messages.

        Handler signature: async def handler(chat_id, user_id, text, metadata) -> reply_text
        """
        self._on_message = handler

    def get_status(self) -> dict:
        """Return channel status info."""
        return {
            "name": self.name,
            "enabled": self.enabled,
        }
