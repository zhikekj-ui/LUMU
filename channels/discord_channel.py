"""Discord channel adapter — uses discord.py library."""
import asyncio
from channels.base import BaseChannel


class DiscordChannel(BaseChannel):
    """Discord Bot adapter using discord.py."""

    name = "discord"

    def __init__(self, token: str):
        super().__init__()
        self._token = token
        self._client = None
        self._task: asyncio.Task | None = None

    async def start(self):
        try:
            import discord
        except ImportError:
            raise RuntimeError("discord.py not installed. Run: pip install discord.py")

        intents = discord.Intents.default()
        intents.message_content = True
        self._client = discord.Client(intents=intents)
        client = self._client
        handler = self._on_message

        @client.event
        async def on_ready():
            print(f"[discord] Connected as {client.user}")
            self.enabled = True

        @client.event
        async def on_message(message):
            # Ignore own messages
            if message.author == client.user:
                return

            # Only respond to mentions or DMs
            is_mention = client.user in message.mentions
            is_dm = isinstance(message.channel, discord.DMChannel)

            if not (is_mention or is_dm):
                return

            # Strip mention from text
            text = message.content
            if is_mention:
                text = text.replace(f"<@{client.user.id}>", "").strip()
            if not text:
                return

            chat_id = str(message.channel.id)
            user_id = str(message.author.id)
            metadata = {
                "username": message.author.name,
                "channel_name": getattr(message.channel, "name", "DM"),
                "message_id": str(message.id),
            }

            if handler:
                reply = await handler(chat_id, user_id, text, metadata)
                if reply:
                    # Discord limit: 2000 chars
                    for i in range(0, len(reply), 2000):
                        await message.channel.send(reply[i:i + 2000])

        self._task = asyncio.create_task(client.start(self._token))

    async def stop(self):
        if self._client:
            await self._client.close()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self.enabled = False

    async def send_message(self, chat_id: str, text: str, reply_to: str | None = None):
        if not self._client:
            return
        channel = self._client.get_channel(int(chat_id))
        if channel:
            for i in range(0, len(text), 2000):
                await channel.send(text[i:i + 2000])

    def get_status(self) -> dict:
        return {
            "name": self.name,
            "enabled": self.enabled,
            "platform": "discord",
        }
