from typing import NoReturn

import aiohttp
from meerkat import Fetcher

from job_monitor.model import Job
from job_monitor.utils import Delayer


class BittenFruitFetcher(Fetcher[Job, NoReturn]):
    def __init__(self, client: aiohttp.ClientSession, delayer: Delayer) -> None:
        self._client = client
        self._delayer = delayer

    def get_class(self) -> type[Job]:
        return Job

    async def run(self) -> dict[Job.Id, Job]:
        raise NotImplementedError(
            "Implement yout totally-TOS-compliant fetcher here.\n"
            "You might want to:\n"
            "- retrieve a CSRF token and use it as header in requests\n"
            "- cycle through pages to get all jobs\n"
            "...or, you could reach out to niqodea and ask for help!"
        )
