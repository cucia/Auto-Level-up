import asyncio
import logging
import os
import signal

import httpx
import discord
from dotenv import load_dotenv

from text_module import TextModule
from voice_module import VoiceModule


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


load_dotenv()
setup_logging(os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("main")


# =========================================================
# Discord Gateway
# =========================================================

class DiscordGateway:
    """
    Thin wrapper around discord.Client.
    Text-only users can ignore voice-related methods.
    """

    def __init__(self, token: str):
        self.token = token
        self.client: discord.Client | None = None
        self.user_id: int | None = None
        self.ready = False

    async def connect(self) -> bool:
        try:
            self.client = discord.Client()

            @self.client.event
            async def on_connect():
                self.user_id = self.client.user.id
                self.ready = True
                logger.info("Connected as user ID %s", self.user_id)

            asyncio.create_task(self.client.start(self.token))

            # Wait up to 30 seconds for ready
            for _ in range(60):
                if self.ready:
                    return True
                await asyncio.sleep(0.5)

            logger.error("Gateway connection timeout")
            return False

        except Exception as e:
            logger.error("Gateway connection failed: %s", e)
            return False

    # ---------- Text helpers ----------

    async def send_message(self, channel_id: int, content: str):
        try:
            channel = self.client.get_channel(channel_id)
            if channel:
                msg = await channel.send(content)
                return msg.id
        except Exception as e:
            logger.error("Send message failed: %s", e)
        return None

    async def delete_message(self, channel_id: int, message_id: int):
        try:
            channel = self.client.get_channel(channel_id)
            if channel:
                msg = await channel.fetch_message(message_id)
                await msg.delete()
        except Exception as e:
            logger.error("Delete message failed: %s", e)

    # ---------- Voice helpers (safe to ignore if unused) ----------

    async def join_vc(self, vc_id: int) -> bool:
        try:
            await self.leave_vc()
            vc = self.client.get_channel(vc_id)
            if vc and isinstance(vc, discord.VoiceChannel):
                await vc.connect()
                logger.info("Joined VC %s", vc_id)
                return True
        except Exception as e:
            logger.warning("Join VC failed: %s", e)
        return False

    async def leave_vc(self):
        try:
            for vc in list(self.client.voice_clients):
                await vc.disconnect(force=True)
        except Exception:
            pass

    async def close(self):
        if self.client:
            await self.client.close()


# =========================================================
# Automation Controller
# =========================================================

class LevelingAutomation:
    """
    Central controller.
    Text and Voice modules are intentionally separated
    so either can be disabled cleanly.
    """

    def __init__(self):
        self.gateway: DiscordGateway | None = None
        self.text_module: TextModule | None = None
        self.voice_module: VoiceModule | None = None

    async def initialize(self) -> bool:
        logger.info("Initializing automation")

        token = os.getenv("DISCORD_TOKEN")
        if not token:
            logger.error("DISCORD_TOKEN missing")
            return False

        # Validate token early
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(
                    "https://discord.com/api/v10/users/@me",
                    headers={"Authorization": token.strip()},
                )
                if r.status_code != 200:
                    logger.error("Invalid Discord token")
                    return False
        except Exception as e:
            logger.error("Token validation failed: %s", e)
            return False

        self.gateway = DiscordGateway(token.strip())

        # Shared config passed to modules
        config = {
            "TARGET_CHANNELS": os.getenv("TARGET_CHANNELS", ""),
            "TARGET_VCS": os.getenv("TARGET_VCS", ""),
            "TEXT_INTERVAL_SEC": os.getenv("TEXT_INTERVAL_SEC", "100"),
            "TEXT_JITTER_SEC": os.getenv("TEXT_JITTER_SEC", "0"),
            "TEXT_DELETE_ENABLED": os.getenv("TEXT_DELETE_ENABLED", "true"),
            "TEXT_AUTO_DELETE_SEC": os.getenv("TEXT_AUTO_DELETE_SEC", "3"),
        }

        # ---- Module wiring (easy to comment out) ----
        self.text_module = TextModule(self.gateway, config)
        self.voice_module = VoiceModule(self.gateway, config)

        logger.info("Initialization complete")
        return True

    async def run(self):
        mode = os.getenv("LEVELING_MODE", "both").lower()
        logger.info("Starting mode: %s", mode)

        if not await self.gateway.connect():
            return

        tasks: list[asyncio.Task] = []

        # ================= TEXT MODE =================
        if mode in ("text", "both"):
            logger.info("Text module enabled")
            tasks.append(asyncio.create_task(self.text_module.run()))

        # ================= VOICE MODE =================
        if mode in ("voice", "both"):
            logger.info("Voice module enabled")
            tasks.append(asyncio.create_task(self.voice_module.run()))

        # If someone wants TEXT-ONLY:
        #   → comment the VOICE block above
        #   → no voice code will execute

        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            logger.info("Tasks cancelled")

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
    automation = LevelingAutomation()

    if not await automation.initialize():
        return

    loop = asyncio.get_running_loop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(
            sig, lambda: asyncio.create_task(automation.shutdown())
        )

    await automation.run()


if __name__ == "__main__":
    asyncio.run(main())
