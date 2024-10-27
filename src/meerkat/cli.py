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
        stdin, _ = await aioconsole.get_standard_streams()
        stdin_fd = sys.stdin.fileno()
        return ClearScreenListener(
            stdin=stdin,
            canonical_mode_disabler=CanonicalModeDisabler(stdin_fd=stdin_fd),
        )


class MeerkatCliLauncher:
    def __init__(
        self,
        meerkats: list[Meerkat],
        clear_screen_listener: ClearScreenListener,
    ) -> None:
        self._meerkats = meerkats
        self._clear_screen_listener = clear_screen_listener

    async def run(self) -> None:
        await asyncio.gather(
            *[meerkat.run() for meerkat in self._meerkats],
            self._clear_screen_listener.run(),
        )

    @dataclass
    class Config(Generic[T, TSE]):
        truth_source_fetcher: TruthSourceFetcher[T, TSE]
        stringifier: Callable[[T], str]
        snapshot_path: Path

    @staticmethod
    async def create(
        configs: dict[str, MeerkatCliLauncher.Config], interval_seconds: int
    ) -> MeerkatCliLauncher:
        logger = Logger.with_default_handlers(name="meerkat")

        meerkats = []
        for name, config in configs.items():
            meerkat: Meerkat = Meerkat(
                truth_source_fetcher=config.truth_source_fetcher,
                truth_source_error_handler=BaseTruthSourceErrorHandler(
                    name=name, logger=logger
                ),
                snapshot_manager=BaseSnapshotManager.create(
                    class_=config.truth_source_fetcher.get_class(),
                    path=config.snapshot_path,
                ),
                action_executor=BaseActionExecutor(
                    name=name,
                    stringifier=config.stringifier,
                    logger=logger,
                ),
                interval_manager=BaseIntervalManager(interval_seconds=interval_seconds),
            )
            meerkats.append(meerkat)

        clear_screen_listener = await ClearScreenListener.create()

        return MeerkatCliLauncher(
            meerkats=meerkats,
            clear_screen_listener=clear_screen_listener,
        )
