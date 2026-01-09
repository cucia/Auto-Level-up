import asyncio
import logging
import time

logger = logging.getLogger("voice_module")


class VoiceModule:
    def __init__(self, gateway, config: dict):
        self.gateway = gateway
        self.config = config
        self.running = False

        vcs = config.get("TARGET_VCS", "")
        self.vc_id = int(vcs.split(",")[0].strip()) if vcs else None

        self.retry_interval = 60          # retry after failure (seconds)
        self.connected_reset = 3000       # reconnect after success (1 hour)

    # ---------- helpers ----------

    def _get_active_voice_client(self):
        if not self.gateway.client:
            return None

        for vc in self.gateway.client.voice_clients:
            if vc.is_connected():
                return vc
        return None

    async def _cleanup_voice_clients(self):
        if not self.gateway.client:
            return

        for vc in list(self.gateway.client.voice_clients):
            try:
                await vc.disconnect(force=True)
            except Exception:
                pass

        # allow aiohttp sockets to close properly
        await asyncio.sleep(3)

    # ---------- main loop ----------

    async def run(self):
        if not self.vc_id:
            logger.error("VoiceModule: TARGET_VCS not configured")
            return

        self.running = True
        logger.info("Voice Module started")
        logger.info("Target VC: %s", self.vc_id)
        logger.info("Retry interval: %s sec", self.retry_interval)
        logger.info("Reconnect after success: %s sec", self.connected_reset)

        connected_since = None

        while self.running:
            try:
                vc = self._get_active_voice_client()

                # -------- connected state --------
                if vc:
                    if connected_since is None:
                        connected_since = time.time()
                        logger.info("Voice connected successfully")

                    # stay connected for 1 hour
                    elapsed = time.time() - connected_since
                    if elapsed >= self.connected_reset:
                        logger.info("1 hour reached, reconnecting VC")
                        await self._cleanup_voice_clients()
                        connected_since = None
                        await asyncio.sleep(self.retry_interval)
                    else:
                        await asyncio.sleep(30)
                    continue

                # -------- not connected --------
                connected_since = None

                # clean up any ghost clients
                await self._cleanup_voice_clients()

                logger.info("Attempting to join VC %s", self.vc_id)
                await self.gateway.join_vc(self.vc_id)

                # wait before next evaluation
                await asyncio.sleep(self.retry_interval)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("VoiceModule error: %s", e)
                await asyncio.sleep(self.retry_interval)

        logger.info("Voice Module loop exited")

    async def stop(self):
        self.running = False
        await self._cleanup_voice_clients()
        logger.info("Voice Module stopped")
