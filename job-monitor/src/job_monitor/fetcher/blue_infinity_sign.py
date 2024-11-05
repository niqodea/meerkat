from typing import NoReturn

import aiohttp
from meerkat import Fetcher

from job_monitor.model import Job


class BlueInfinitySignFetcher(Fetcher[Job, NoReturn]):
    def __init__(self, client: aiohttp.ClientSession) -> None:
        self._client = client

    def get_class(self) -> type[Job]:
        return Job

    async def run(self) -> dict[Job.Id, Job]:
        raise NotImplementedError(
            "Implement yout totally-TOS-compliant fetcher here.\n"
            "You might want to:\n"
            "- retrieve datr and lsd from landing page\n"
            "- use them in the request to retrieve jobs\n"
            "...or, you could reach out to niqodea and ask for help!"
        )
