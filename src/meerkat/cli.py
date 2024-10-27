from __future__ import annotations

import asyncio
import sys
import termios
from dataclasses import dataclass
from typing import Callable, Generic, Self

import aioconsole
from aiologger import Logger
from aiopath import Path

from meerkat.core import (
    TSE,
    BaseActionExecutor,
    BaseIntervalManager,
    BaseSnapshotManager,
    BaseTruthSourceErrorHandler,
    Meerkat,
    T,
    TruthSourceFetcher,
)


class CanonicalModeDisabler:
    """
    Context manager that temporarily disables canonical mode in the terminal.
    """

    def __init__(self, stdin_fd: int) -> None:
        self._stdin_fd = stdin_fd

    def __enter__(self) -> Self:
        self._original_settings: list[int | list[bytes]] = termios.tcgetattr(
            self._stdin_fd
        )

        override_settings = self._original_settings

        override_flags: int = override_settings[3]  # type: ignore[assignment]
        override_flags &= ~termios.ICANON
        override_settings[3] = override_flags

        termios.tcsetattr(self._stdin_fd, termios.TCSADRAIN, override_settings)

        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        termios.tcsetattr(self._stdin_fd, termios.TCSADRAIN, self._original_settings)


class ClearScreenListener:
    """
    Listens for CTRL+L and sends the escape codes to clear the screen.
    """

    def __init__(
        self,
        stdin: asyncio.StreamReader,
        canonical_mode_disabler: CanonicalModeDisabler,
    ) -> None:
        self._stdin = stdin
        self._canonical_mode_disabler = canonical_mode_disabler

    async def run(self) -> None:
        with self._canonical_mode_disabler:
            try:
                while True:
                    if await self._stdin.read(1) == self.TRIGGER:
                        print(self.ESCAPE_CODES, end="", flush=True)
            except asyncio.CancelledError:
                pass

    TRIGGER = b"\x0c"  # CTRL+L
    ESCAPE_CODES = "\033[H\033[J"  # move cursor to top left + clear screen

    @staticmethod
    async def create() -> ClearScreenListener:
        """
        Create an instance of ClearScreenListener for stdin/stdout.

        :return: Created instance.
        """
        stdin, _ = await aioconsole.get_standard_streams()
        stdin_fd = sys.stdin.fileno()
        return ClearScreenListener(
            stdin=stdin,
            canonical_mode_disabler=CanonicalModeDisabler(stdin_fd=stdin_fd),
        )


class CliDeployer:
    """
    Deploys a CLI environment with meerkats that report changes to stdout.
    """

    def __init__(
        self,
        meerkats: list[Meerkat],
        clear_screen_listener: ClearScreenListener,
    ) -> None:
        """
        :param meerkats: Meerkats to run.
        :param clear_screen_listener: Key listener for clearing terminal screen.
        """
        self._meerkats = meerkats
        self._clear_screen_listener = clear_screen_listener

    async def run(self) -> None:
        """
        Deploy the configured CLI environment.
        """
        await asyncio.gather(
            *[meerkat.run() for meerkat in self._meerkats],
            self._clear_screen_listener.run(),
        )

    @dataclass
    class MeerkatSpec(Generic[T, TSE]):
        """
        Specification of a meerkat to run.
        """

        truth_source_fetcher: TruthSourceFetcher[T, TSE]
        """
        Fetcher for the truth source.
        """
        stringifier: Callable[[T], str]
        """
        Function to convert things to strings to display in stdout.
        """
        snapshot_path: Path
        """
        Path to the directory where things are tracked as JSON files.
        """
        interval_seconds: int
        """
        Interval in seconds between monitoring sessions.
        """

    @staticmethod
    async def create(meerkat_specs: dict[str, CliDeployer.MeerkatSpec]) -> CliDeployer:
        """
        Create an instance of CliDeployer.

        :param meerkat_specs: Specifications of the meerkats to run, indexed by the
            name of the domain of things each meerkat operates in.
        :return: Created instance.
        """
        logger = Logger.with_default_handlers(name="meerkat")

        meerkats = []
        for domain_name, spec in meerkat_specs.items():
            meerkat: Meerkat = Meerkat(
                truth_source_fetcher=spec.truth_source_fetcher,
                truth_source_error_handler=BaseTruthSourceErrorHandler(
                    domain_name=domain_name, logger=logger
                ),
                snapshot_manager=await BaseSnapshotManager.create(
                    class_=spec.truth_source_fetcher.get_class(),
                    path=spec.snapshot_path,
                ),
                action_executor=BaseActionExecutor(
                    domain_name=domain_name,
                    stringifier=spec.stringifier,
                    logger=logger,
                ),
                interval_manager=BaseIntervalManager(
                    interval_seconds=spec.interval_seconds
                ),
            )
            meerkats.append(meerkat)

        clear_screen_listener = await ClearScreenListener.create()

        return CliDeployer(
            meerkats=meerkats,
            clear_screen_listener=clear_screen_listener,
        )
