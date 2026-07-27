"""Telegram channel adapter — uses Bot API with long polling (no extra dependencies)."""
import asyncio
import aiohttp
from channels.base import BaseChannel

TELEGRAM_API = "https://api.telegram.org/bot{token}"


class TelegramChannel(BaseChannel):
    """Telegram Bot adapter using long polling via aiohttp."""

    name = "telegram"

    def __init__(self, token: str):
        super().__init__()
        self._token = token
        self._base_url = TELEGRAM_API.format(token=token)
        self._running = False
        self._task: asyncio.Task | None = None
        self._offset = 0
        self._session: aiohttp.ClientSession | None = None

    async def start(self):
        self._session = aiohttp.ClientSession()
        # Verify bot token
        async with self._session.get(f"{self._base_url}/getMe") as resp:
            data = await resp.json()
            if not data.get("ok"):
                raise RuntimeError(f"Telegram auth failed: {data}")
            bot_name = data["result"].get("username", "?")
            print(f"[telegram] Connected as @{bot_name}")

        self._running = True
        self.enabled = True
        self._task = asyncio.create_task(self._poll_loop())

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._session:
            await self._session.close()
        self.enabled = False

    async def send_message(self, chat_id: str, text: str, reply_to: str | None = None):
        if not self._session:
            return
        payload = {
            "chat_id": chat_id,
            "text": text,
        }
        if reply_to:
            payload["reply_to_message_id"] = reply_to
        # Split long messages (Telegram limit: 4096 chars)
        for i in range(0, len(text), 4096):
            payload["text"] = text[i:i + 4096]
            async with self._session.post(f"{self._base_url}/sendMessage", json=payload) as resp:
                await resp.json()

    async def _poll_loop(self):
        """Long polling loop for incoming updates."""
        while self._running:
            try:
                params = {
                    "offset": self._offset,
                    "timeout": 30,
                    "allowed_updates": ["message"],
                }
                async with self._session.get(f"{self._base_url}/getUpdates", params=params, timeout=aiohttp.ClientTimeout(total=40)) as resp:
                    data = await resp.json()

                if data.get("ok"):
                    for update in data.get("result", []):
                        self._offset = update["update_id"] + 1
                        message = update.get("message")
                        if message and message.get("text"):
                            await self._process_message(message)
            except asyncio.CancelledError:
                break
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                print(f"[telegram] Poll error: {e}")
                await asyncio.sleep(5)

    async def _process_message(self, message: dict):
        """Process a single Telegram message."""
        chat_id = str(message["chat"]["id"])
        user_id = str(message["from"]["id"])
        text = message["text"]
        msg_id = str(message["message_id"])

        metadata = {
            "username": message["from"].get("username", ""),
            "first_name": message["from"].get("first_name", ""),
            "message_id": msg_id,
        }

        if self._on_message:
            reply = await self._on_message(chat_id, user_id, text, metadata)
            if reply:
                await self.send_message(chat_id, reply, reply_to=msg_id)

    def get_status(self) -> dict:
        return {
            "name": self.name,
            "enabled": self.enabled,
            "platform": "telegram",
        }
