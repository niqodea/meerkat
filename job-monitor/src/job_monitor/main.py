import asyncio

import aiohttp
from meerkat import Fetcher
from meerkat.cli import CliDeployer

from job_monitor.fetcher import (
    BittenFruitFetcher,
    BlueInfinitySignFetcher,
    GreenEyeFetcher,
    MultiColorGFetcher,
    RedArcNFetcher,
)
from job_monitor.model import JobStringifier
from job_monitor.path import DATA_PATH
from job_monitor.utils import Delayer


async def main() -> None:
    async with aiohttp.ClientSession() as client:
        delayer = Delayer(min_seconds=1.0, max_seconds=2.0)
        fetchers: dict[str, Fetcher] = {
            "bitten-fruit": BittenFruitFetcher(client, delayer=delayer),
            "blue-infinity-sign": BlueInfinitySignFetcher(client),
            "green-eye": GreenEyeFetcher(client, delayer=delayer),
            "multi-color-g": MultiColorGFetcher(client, delayer=delayer),
            "red-arc-n": RedArcNFetcher(client, delayer=delayer),
        }

        stringifier = JobStringifier.create(
            highlight_terms={
                "ai",
                "aiml",
                "artificial intelligence",
                "computer vision",
                "cv",
                "deep learning",
                "genai",
                "large language model",
                "llm",
                "machine learning",
                "ml",
            },
        )

        specs = {}
        for company, fetcher in fetchers.items():
            snapshot_path = DATA_PATH / company
            await snapshot_path.mkdir(exist_ok=True)
            specs[company] = CliDeployer.MeerkatSpec(
                fetcher=fetcher,
                stringifier=stringifier,
                snapshot_path=snapshot_path,
                interval_seconds=3600,
            )

        deployer = await CliDeployer.create(specs)

        await deployer.run()


if __name__ == "__main__":
    asyncio.run(main())
