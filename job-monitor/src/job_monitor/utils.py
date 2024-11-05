import asyncio
import random


# Used to mimic human behavior when scraping through pages
# Ref: https://www.reddit.com/r/webscraping/comments/m8b05v
class Delayer:
    def __init__(self, min_seconds: float, max_seconds: float) -> None:
        self._min_seconds = min_seconds
        self._max_seconds = max_seconds

    async def run(self) -> None:
        seconds = random.uniform(self._min_seconds, self._max_seconds)
        await asyncio.sleep(seconds)
