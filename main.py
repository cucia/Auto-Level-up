import asyncio
import logging
import os
import signal

import discord
from dotenv import load_dotenv

# =========================================================
# Logging
# =========================================================

def setup_logging(level_str: str = "INFO"):
    level = getattr(logging, level_str.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler("leveling.log"),
        ],
    )

load_dotenv(dotenv_path=".env", override=True)
setup_logging(os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("main")

# =========================================================
# Discord Gateway
# =========================================================

class DiscordGateway:
    def __init__(self, token: str):
        self.token = token
        self.client: discord.Client | None = None
        self.user_id: int | None = None
        self.ready = False

    async def connect(self) -> bool:
        self.client = discord.Client()

        @self.client.event
        async def on_connect():
            self.user_id = self.client.user.id
            self.ready = True
            logger.info("Connected as user ID %s", self.user_id)

        asyncio.create_task(self.client.start(self.token))

        for _ in range(60):  # ~30 seconds
            if self.ready:
                return True
            await asyncio.sleep(0.5)

        logger.error("Discord gateway connection timeout")
        return False

    # ---------- shared helpers ----------

    async def send_message(self, channel_id: int, content: str):
        channel = self.client.get_channel(channel_id)
        if channel:
            msg = await channel.send(content)
            return msg.id
        return None

    async def delete_message(self, channel_id: int, message_id: int):
        try:
            channel = self.client.get_channel(channel_id)
            if not channel:
                return
            msg = await channel.fetch_message(message_id)
            await msg.delete()
            logger.info("Message %s deleted from channel %s", message_id, channel_id)
        except Exception as e:
            logger.error(
                "Failed to delete message %s from channel %s: %s",
                message_id,
                channel_id,
                e,
            )

    async def join_vc(self, vc_id: int) -> bool:
        try:
            for vc in list(self.client.voice_clients):
                await vc.disconnect(force=True)

            channel = self.client.get_channel(vc_id)
            if isinstance(channel, discord.VoiceChannel):
                await channel.connect()
                logger.info("Joined VC %s", vc_id)
                return True
        except Exception as e:
            logger.warning("Join VC failed: %s", e)
        return False

    def on_voice_state_update(self, callback):
        @self.client.event
        async def on_voice_state_update(member, before, after):
            await callback(member, before, after)

    async def close(self):
        if self.client:
            await self.client.close()

# =========================================================
# Automation Controller
# =========================================================

class LevelingAutomation:
    def __init__(self):
        self.gateway = None
        self.text_module = None
        self.voice_module = None
        self.config = {}

    async def initialize(self) -> bool:
        logger.info("Initializing automation")

        token = os.getenv("DISCORD_TOKEN")
        if not token or not token.strip():
            logger.error("DISCORD_TOKEN missing or empty")
            return False

        self.gateway = DiscordGateway(token.strip())

        # Shared config ONLY (no logic here)
        self.config = {
            "TARGET_CHANNELS": os.getenv("TARGET_CHANNELS", ""),
            "TARGET_VCS": os.getenv("TARGET_VCS", ""),
            "TEXT_INTERVAL_SEC": os.getenv("TEXT_INTERVAL_SEC", "100"),
            "TEXT_JITTER_SEC": os.getenv("TEXT_JITTER_SEC", "0"),
            "TEXT_DELETE_ENABLED": os.getenv("TEXT_DELETE_ENABLED", "true"),
            "TEXT_AUTO_DELETE_SEC": os.getenv("TEXT_AUTO_DELETE_SEC", "3"),
            "VOICE_BASE_STAY_SEC": os.getenv("VOICE_BASE_STAY_SEC", "3600"),
            "VOICE_JITTER_SEC": os.getenv("VOICE_JITTER_SEC", "3600"),
            "VOICE_COOLDOWN_SEC": os.getenv("VOICE_COOLDOWN_SEC", "900"),
            "VOICE_BUSY_RETRY_SEC": os.getenv("VOICE_BUSY_RETRY_SEC", "60"),
            "TIMEZONE": os.getenv("TIMEZONE", "Asia/Kolkata"),
        }

        logger.info("Initialization complete")
        return True

    async def run(self):
        mode = os.getenv("LEVELING_MODE", "both").lower()
        logger.info("Starting mode: %s", mode)

        if not await self.gateway.connect():
            return

        tasks = []

        # -------- TEXT MODE --------
        if mode in ("text", "both"):
            try:
                from text_module import TextModule
                logger.info("Text module enabled")
                self.text_module = TextModule(self.gateway, self.config)
                tasks.append(asyncio.create_task(self.text_module.run()))
            except ImportError as e:
                logger.error("Text module not available: %s", e)

        # -------- VOICE MODE --------
        if mode in ("voice", "both"):
            try:
                from voice_module import VoiceModule
                logger.info("Voice module enabled")
                self.voice_module = VoiceModule(self.gateway, self.config)
                tasks.append(asyncio.create_task(self.voice_module.run()))
            except ImportError as e:
                logger.error("Voice module not available: %s", e)

        if not tasks:
            logger.error("No modules enabled — exiting")
            return

        await asyncio.gather(*tasks)

    async def shutdown(self):
        logger.info("Shutting down")

        if self.text_module:
            await self.text_module.stop()

        if self.voice_module:
            await self.voice_module.stop()

        if self.gateway:
            await self.gateway.close()

        logger.info("Shutdown complete")

# =========================================================
# Entrypoint
# =========================================================

async def main():
    app = LevelingAutomation()

    if not await app.initialize():
        return

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(app.shutdown()))

    await app.run()

if __name__ == "__main__":
    asyncio.run(main())
