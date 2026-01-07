import asyncio
import logging
import os
import signal
import httpx
import discord
from dotenv import load_dotenv

from text_module import TextModule
from voice_module import VoiceModule


def setup_logging(level_str: str = "INFO"):
    """Configure logging."""
    level = getattr(logging, level_str.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler("leveling.log"),
        ],
    )


def parse_config_list(config_str: str) -> list:
    """Parse comma-separated config into list of ints."""
    try:
        return [int(x.strip()) for x in config_str.split(",") if x.strip()]
    except ValueError:
        logger.error("Invalid config list: %s", config_str)
        return []


load_dotenv()
setup_logging(os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("main")


async def exponential_backoff(attempt: int, base: float = 2.0) -> None:
    """Exponential backoff for retries."""
    delay = min(base ** attempt, 60)  # cap at 60s
    logger.info("Backoff: waiting %.1f seconds", delay)
    await asyncio.sleep(delay)


class DiscordGateway:
    def __init__(self, token: str):
        self.token = token
        self.client = None
        self.current_vc_id = None
        self.user_id = None
        self.ready = False

    async def connect(self) -> bool:
        """Connect to Discord Gateway."""
        try:
            self.client = discord.Client()

            @self.client.event
            async def on_connect():
                logger.info("On connect event triggered")
                self.user_id = self.client.user.id
                self.ready = True

            # Start the client
            asyncio.create_task(self.client.start(self.token))
            
            # Wait for connection
            for _ in range(60):  # 30 seconds
                if self.ready:
                    return True
                await asyncio.sleep(0.5)
            
            logger.error("Gateway failed to connect")
            return False
        except Exception as e:
            logger.error("Gateway connection failed: %s", e)
            return False

    async def send_message(self, channel_id: int, content: str):
        """Send message to channel, return message ID."""
        try:
            channel = self.client.get_channel(channel_id)
            if channel:
                msg = await channel.send(content)
                logger.info("Message sent to channel %s, ID: %s", channel_id, msg.id)
                return msg.id
        except Exception as e:
            logger.error("Failed to send message: %s", e)
        return None

    async def delete_message(self, channel_id: int, message_id: int) -> bool:
        """Delete message by ID."""
        try:
            channel = self.client.get_channel(channel_id)
            if channel:
                msg = await channel.fetch_message(message_id)
                await msg.delete()
                logger.info("Message %s deleted", message_id)
                return True
        except Exception as e:
            logger.error("Failed to delete message: %s", e)
        return False

    async def join_vc(self, vc_id: int) -> bool:
        """Join voice channel."""
        try:
            # Ensure not connected to any VC
            await self.leave_vc()
            
            vc = self.client.get_channel(vc_id)
            if vc and isinstance(vc, discord.VoiceChannel):
                for attempt in range(3):
                    try:
                        await vc.connect()
                        self.current_vc_id = vc_id
                        logger.info("Joined VC %s", vc_id)
                        return True
                    except Exception as e:
                        error_str = str(e)
                        if "Already connected" in error_str:
                            logger.warning("Already connected, forcing leave and retry")
                            await self.leave_vc()
                            await asyncio.sleep(1)  # Wait for cleanup
                        else:
                            logger.warning("Voice connect attempt %d failed: %s", attempt + 1, e)
                        if attempt < 2:
                            await asyncio.sleep(5)
                logger.error("Failed to join VC after retries")
            else:
                logger.error("VC %s not found or not a voice channel", vc_id)
        except Exception as e:
            logger.error("Failed to join VC: %s", e)
        return False

    async def leave_vc(self) -> bool:
        """Leave current voice channel immediately."""
        try:
            if self.client.voice_clients:
                for vc in self.client.voice_clients:
                    await vc.disconnect()
                    logger.info("Left VC %s", vc.channel.id)
                self.current_vc_id = None
                return True
        except Exception as e:
            logger.error("Failed to leave VC: %s", e)
        return False

    async def get_vc_users(self, vc_id: int) -> int:
        """Get user count in VC (excluding self)."""
        try:
            vc = self.client.get_channel(vc_id)
            if vc and isinstance(vc, discord.VoiceChannel):
                count = len([m for m in vc.members if m.id != self.user_id])
                return count
        except Exception as e:
            logger.error("Failed to get VC users: %s", e)
        return -1

    def on_voice_state_update(self, callback):
        """Register voice state update handler."""
        @self.client.event
        async def voice_state_update_handler(member, before, after):
            await callback(member, before, after)


class LevelingAutomation:
    def __init__(self):
        self.gateway = None
        self.text_module = None
        self.voice_module = None
        self.running = False

    async def initialize(self) -> bool:
        """Initialize all components."""
        logger.info("Initializing Leveling Automation...")

        # Authenticate
        token = os.getenv("DISCORD_TOKEN")
        if not token:
            logger.error("No DISCORD_TOKEN in .env")
            return False
        token = token.strip()
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                headers = {"Authorization": token}
                resp = await client.get("https://discord.com/api/v10/users/@me", headers=headers)
                if resp.status_code != 200:
                    logger.error("Invalid token")
                    return False
        except Exception as e:
            logger.error("Token validation failed: %s", e)
            return False

        # Setup Gateway
        self.gateway = DiscordGateway(token)
        logger.info("Gateway initialized")

        # Setup Modules
        config = {
            "TARGET_CHANNELS": os.getenv("TARGET_CHANNELS", ""),
            "TARGET_VCS": os.getenv("TARGET_VCS", ""),
            "TEXT_INTERVAL_SEC": os.getenv("TEXT_INTERVAL_SEC", "100"),
            "TEXT_JITTER_SEC": os.getenv("TEXT_JITTER_SEC", "0"),
            "TEXT_DELETE_ENABLED": os.getenv("TEXT_DELETE_ENABLED", "true"),
            "TEXT_AUTO_DELETE_SEC": os.getenv("TEXT_AUTO_DELETE_SEC", "3"),
            "VOICE_ROTATION_HOURS": os.getenv("VOICE_ROTATION_HOURS", "1"),
            "VOICE_CHECK_INTERVAL_SEC": os.getenv("VOICE_CHECK_INTERVAL_SEC", "5"),
        }

        self.text_module = TextModule(self.gateway, config)
        self.voice_module = VoiceModule(self.gateway, config)

        logger.info("Initialization complete")
        return True

    async def run(self):
        """Run automation based on LEVELING_MODE."""
        mode = os.getenv("LEVELING_MODE", "both").lower()
        self.running = True

        logger.info("Starting mode: %s", mode)

        tasks = []

        # Start Gateway connection
        if not await self.gateway.connect():
            logger.error("Failed to connect to gateway")
            return

        # Start modules
        if mode in ["text", "both"]:
            tasks.append(asyncio.create_task(self.text_module.run()))

        if mode in ["voice", "both"]:
            tasks.append(asyncio.create_task(self.voice_module.run()))

        logger.info("All modules running")

        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            logger.info("Tasks cancelled")


    async def shutdown(self):
        """Clean shutdown."""
        logger.info("Shutting down...")
        self.running = False

        if self.text_module:
            await self.text_module.stop()
        if self.voice_module:
            await self.voice_module.stop()
        if self.gateway:
            await self.gateway.close()

        logger.info("Shutdown complete")


async def main():
    automation = LevelingAutomation()

    if not await automation.initialize():
        return

    # Handle signals
    def signal_handler(sig, frame):
        asyncio.create_task(automation.shutdown())

    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    await automation.run()


if __name__ == "__main__":
    asyncio.run(main())
