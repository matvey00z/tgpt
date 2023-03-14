import time
import asyncio
import logging

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.DEBUG,
)


class Limiter:
    def __init__(self, limits, interval):
        self.time_per_volume = {k: interval / v for (k, v) in limits.items()}
        logging.debug(
            f"Limiter: init with limits {limits}, interval {interval}, time per volume {self.time_per_volume}"
        )

        self.next = time.monotonic()
        self.lock = asyncio.Lock()

    async def run(self, f, volume):
        duration = max((v * self.time_per_volume[k] for (k, v) in volume.items()))
        now = time.monotonic()
        async with self.lock:
            target = max(self.next, now)
            self.next = target + duration
        to_sleep = target - now
        logging.debug(
            f"Limiter: run with volume {volume}, duration {duration}, now {now}, sleep until {target}"
        )
        if to_sleep > 0:
            await asyncio.sleep(to_sleep)
        return await f

    async def alloc(self, volume):
        duration = max((v * self.time_per_volume[k] for (k, v) in volume.items()))
        logging.debug(f"Limiter: alloc with volume {volume}, duration {duration}")
        async with self.lock:
            self.next += duration
