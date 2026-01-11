import asyncio
import logging
import random
import time
from datetime import datetime, time as dtime
import pytz
import discord

logger = logging.getLogger("voice_module")


# ======================================================
# Silent Audio Source (CRITICAL)
# ======================================================

class SilentAudio(discord.AudioSource):
    def read(self):
        return b'\x00' * 3840  # 20ms of silence (Opus frame size)

    def is_opus(self):
        return True


# ======================================================
# Voice Module
# ======================================================

class VoiceModule:
    def __init__(self, gateway, config: dict):
        self.gateway = gateway
        self.running = False

        # ---- config ----
        self.vc_id = int(config.get("TARGET_VCS"))
        self.base_stay = int(config.get("VOICE_BASE_STAY_SEC", 3600))
        self.jitter = int(config.get("VOICE_JITTER_SEC", 3600))
        self.cooldown = int(config.get("VOICE_COOLDOWN_SEC", 900))
        self.busy_retry = int(config.get("VOICE_BUSY_RETRY_SEC", 60))
        self.tz = pytz.timezone(config.get("TIMEZONE", "Asia/Kolkata"))

        # ---- state ----
        self.state = "IDLE"
        self.connected_since = None
        self.audio_task = None

    # --------------------------------------------------
    # Helpers
    # --------------------------------------------------

    def now_ist(self):
        return datetime.now(self.tz).time()

    def in_night_window(self):
        now = self.now_ist()
        return dtime(2, 0) <= now < dtime(7, 0)

    def get_target_vc(self):
        ch = self.gateway.client.get_channel(self.vc_id)
        return ch if isinstance(ch, discord.VoiceChannel) else None

    def active_voice_client(self):
        for vc in self.gateway.client.voice_clients:
            if vc.is_connected():
                return vc
        return None

    async def leave_voice(self):
        self.stop_audio()

        for vc in list(self.gateway.client.voice_clients):
            try:
                await vc.disconnect(force=True)
            except Exception:
                pass

        await asyncio.sleep(2)
        self.connected_since = None

    # --------------------------------------------------
    # Silent audio keep-alive
    # --------------------------------------------------

    def start_audio(self):
        vc = self.active_voice_client()
        if not vc:
            return

        if vc.is_playing():
            return

        logger.info("Starting silent audio keep-alive")
        vc.play(SilentAudio())

    def stop_audio(self):
        vc = self.active_voice_client()
        if vc and vc.is_playing():
            logger.info("Stopping silent audio")
            vc.stop()

    # --------------------------------------------------
    # Voice event hook
    # --------------------------------------------------

    async def on_voice_state_update(self, member, before, after):
        me = self.gateway.user_id

        # ----- manual override -----
        if member.id == me:
            if after.channel and after.channel.id != self.vc_id:
                if self.state != "MANUAL_SLEEP":
                    logger.info("Manual VC detected → automation sleeping")
                    self.state = "MANUAL_SLEEP"
                    await self.leave_voice()

            elif after.channel is None and self.state == "MANUAL_SLEEP":
                logger.info("Manual session ended → automation resuming")
                self.state = "IDLE"

        # ----- someone joined while connected -----
        if (
            member.id != me
            and after.channel
            and after.channel.id == self.vc_id
            and self.state == "CONNECTED"
        ):
            logger.info("User joined target VC → exiting immediately")
            await self.leave_voice()
            self.state = "BUSY_WAIT"

    # --------------------------------------------------
    # Main loop
    # --------------------------------------------------

    async def run(self):
        self.running = True
        self.gateway.on_voice_state_update(self.on_voice_state_update)

        logger.info("Voice Module v1 started (single VC)")
        logger.info("Target VC: %s", self.vc_id)

        while self.running:
            try:
                if self.state == "MANUAL_SLEEP":
                    await asyncio.sleep(10)
                    continue

                vc = self.get_target_vc()
                if not vc:
                    logger.error("Target VC not found")
                    await asyncio.sleep(60)
                    continue

                if self.state == "BUSY_WAIT":
                    if len(vc.members) == 0:
                        logger.info("Target VC empty → retrying join")
                        self.state = "IDLE"
                    else:
                        await asyncio.sleep(self.busy_retry)
                        continue

                if self.active_voice_client():
                    await asyncio.sleep(15)
                    continue

                logger.info("Attempting to join target VC")
                await self.gateway.join_vc(self.vc_id)

                vc_client = self.active_voice_client()
                if not vc_client:
                    logger.info("Join failed → retry in %s sec", self.busy_retry)
                    self.state = "BUSY_WAIT"
                    await asyncio.sleep(self.busy_retry)
                    continue

                # ----- connected -----
                self.connected_since = time.time()
                self.state = "CONNECTED"
                logger.info("Voice connected successfully")

                # 🔒 START SILENT AUDIO (FIX)
                self.start_audio()

                # ----- stay logic -----
                if self.in_night_window():
                    logger.info("Night window (2–7 AM IST) → staying connected")
                    while self.running and self.state == "CONNECTED" and self.in_night_window():
                        await asyncio.sleep(30)
                else:
                    stay_time = self.base_stay + random.randint(0, self.jitter)
                    logger.info("Staying for %s seconds", stay_time)
                    while self.running and self.state == "CONNECTED":
                        if time.time() - self.connected_since >= stay_time:
                            break
                        await asyncio.sleep(30)

                # ----- leave -----
                if self.state == "CONNECTED":
                    logger.info("Leaving VC (cycle complete)")
                    await self.leave_voice()
                    self.state = "IDLE"
                    await asyncio.sleep(self.cooldown)

            except Exception as e:
                logger.error("Voice module error: %s", e)
                await asyncio.sleep(60)

    async def stop(self):
        self.running = False
        await self.leave_voice()
        logger.info("Voice Module stopped")
