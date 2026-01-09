import logging
import asyncio
import random
import aiofiles
import discord
from datetime import timedelta

logger = logging.getLogger("text_module")


def get_jittered_interval(base_sec: float, jitter_sec: float) -> float:
    return base_sec + random.uniform(0, jitter_sec)


def parse_config_list(config_str: str) -> list:
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

        self.min_idle_sec = 300      # 5 minutes
        self.no_vc_sleep_sec = 600   # 10 minutes

    async def load_greetings(self):
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
        self.running = True
        logger.info("Text Module started")

        await self.load_greetings()

        vc_ids = parse_config_list(self.config.get("TARGET_CHANNELS", ""))
        if not vc_ids:
            logger.error("No TARGET_CHANNELS configured")
            return

        base_interval = float(self.config.get("TEXT_INTERVAL_SEC", 100))
        jitter = float(self.config.get("TEXT_JITTER_SEC", 0))
        delete_enabled = self.config.get("TEXT_DELETE_ENABLED", "true").lower() == "true"
        delete_sec = float(self.config.get("TEXT_AUTO_DELETE_SEC", 3))

        while self.running:
            try:
                random.shuffle(vc_ids)
                sent = False

                for vc_id in vc_ids:
                    vc = self.gateway.client.get_channel(vc_id)

                    if not vc or not isinstance(vc, discord.VoiceChannel):
                        continue

                    # ---- Condition 1: VC must be empty ----
                    if len(vc.members) > 0:
                        logger.info(
                            "Skipping VC %s → %d users present",
                            vc_id,
                            len(vc.members),
                        )
                        continue

                    # ---- Condition 2: Chat must be idle ≥ 5 min ----
                    last_msg = None
                    async for msg in vc.history(limit=1):
                        last_msg = msg
                        break

                    if last_msg:
                        age = (
                            discord.utils.utcnow() - last_msg.created_at
                        ).total_seconds()
                        if age < self.min_idle_sec:
                            logger.info(
                                "Skipping VC %s → last message %.1fs ago",
                                vc_id,
                                age,
                            )
                            continue

                    # ---- Send message ----
                    greeting = random.choice(self.greetings)
                    msg_id = await self.gateway.send_message(vc_id, greeting)

                    if msg_id:
                        logger.info(
                            "Message sent | VC=%s | msg_id=%s | content=%.40s",
                            vc_id,
                            msg_id,
                            greeting,
                        )

                        if delete_enabled and delete_sec > 0:
                            logger.info(
                                "Auto-delete scheduled | VC=%s | msg_id=%s | %.2fs",
                                vc_id,
                                msg_id,
                                delete_sec,
                            )
                            await asyncio.sleep(delete_sec)
                            await self.gateway.delete_message(vc_id, msg_id)
                            logger.info(
                                "Message auto-deleted | VC=%s | msg_id=%s",
                                vc_id,
                                msg_id,
                            )

                        sent = True
                        break

                if not sent:
                    logger.info(
                        "No eligible voice chats → sleeping %d seconds",
                        self.no_vc_sleep_sec,
                    )
                    await asyncio.sleep(self.no_vc_sleep_sec)
                    continue

                wait_time = get_jittered_interval(base_interval, jitter)
                logger.info("Next message in %.1f seconds", wait_time)
                await asyncio.sleep(wait_time)

            except Exception as e:
                logger.error("Text module error: %s", e)
                await asyncio.sleep(5)

    async def stop(self):
        self.running = False
        logger.info("Text Module stopped")
