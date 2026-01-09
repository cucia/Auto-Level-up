import logging
import asyncio
import random
import aiofiles

logger = logging.getLogger("text_module")


def get_jittered_interval(base_sec: float, jitter_sec: float) -> float:
    """Get random interval with jitter (in seconds)."""
    return base_sec + random.uniform(0, jitter_sec)


def parse_config_list(config_str: str) -> list:
    """Parse comma-separated config into list of ints."""
    try:
        return [int(x.strip()) for x in config_str.split(",") if x.strip()]
    except ValueError:
        logger.error("Invalid config list: %s", config_str)
        return []


class TextModule:
    def __init__(self, gateway, config: dict):
        self.gateway = gateway
        self.config = config
        self.running = False
        self.greetings = []

    async def load_greetings(self):
        """Load greetings from file."""
        try:
            greeting_file = self.config.get("GREETING_FILE", "greetings.txt")
            async with aiofiles.open(greeting_file, "r", encoding="utf-16") as f:
                content = await f.read()
                self.greetings = [
                    line.strip()
                    for line in content.split("\n")
                    if line.strip() and len(line.strip()) >= 25
                ]
                logger.info("Loaded %d greetings", len(self.greetings))
        except Exception as e:
            logger.error("Failed to load greetings: %s", e)
            self.greetings = ["Keep grinding, you got this!"]

    async def run(self):
        """Main text module loop."""
        self.running = True
        logger.info("Text Module started")

        # Load greetings on startup
        await self.load_greetings()

        channels = parse_config_list(self.config.get("TARGET_CHANNELS", ""))
        if not channels:
            logger.error("No target channels configured")
            return

        base_interval = float(self.config.get("TEXT_INTERVAL_SEC", 100))
        jitter = float(self.config.get("TEXT_JITTER_SEC", 0))
        delete_enabled = self.config.get("TEXT_DELETE_ENABLED", "true").lower() == "true"
        delete_sec = float(self.config.get("TEXT_AUTO_DELETE_SEC", 3))

        while self.running:
            try:
                # Pick random channel & message
                channel_id = random.choice(channels)
                greeting = random.choice(self.greetings)

                # Send message
                msg_id = await self.gateway.send_message(channel_id, greeting)

                if msg_id:
                    logger.info(
                        "Message sent | channel=%s | msg_id=%s | content=%.40s",
                        channel_id,
                        msg_id,
                        greeting,
                    )

                    # Auto-delete if enabled
                    if delete_enabled and delete_sec > 0:
                        logger.info(
                            "Auto-delete scheduled | channel=%s | msg_id=%s | delay=%.2f sec",
                            channel_id,
                            msg_id,
                            delete_sec,
                        )

                        await asyncio.sleep(delete_sec)
                        await self.gateway.delete_message(channel_id, msg_id)

                        logger.info(
                            "Message auto-deleted | channel=%s | msg_id=%s",
                            channel_id,
                            msg_id,
                        )

                # Wait for next interval
                wait_time = get_jittered_interval(base_interval, jitter)
                logger.info("Next message in %.1f seconds", wait_time)
                await asyncio.sleep(wait_time)

            except Exception as e:
                logger.error("Text module error: %s", e)
                await asyncio.sleep(5)

    async def stop(self):
        """Stop text module."""
        self.running = False
        logger.info("Text Module stopped")
