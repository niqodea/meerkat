from __future__ import annotations

import asyncio
import sys
import termios
import traceback
from dataclasses import dataclass
from datetime import datetime
from typing import Generic, Protocol, Self

import aioconsole
from aiologger import Logger
from aiopath import Path

from meerkat.core import (
    FE,
    ActionExecutor,
    BasicFetchError,
    CreateOperation,
    DeleteOperation,
    FE_contravariant,
    Fetcher,
    FetchErrorHandler,
    FixedTimeIntervalManager,
    JsonSnapshotManager,
    Meerkat,
    Operation,
    T,
    T_contravariant,
    Thing,
    UpdateOperation,
)


class CanonicalModeDisabler:
    """
    Context manager that temporarily disables canonical mode in the terminal.
    """

    def __init__(self, stdin_fd: int) -> None:
        """
        :param stdin_fd: File descriptor of the stdin stream.
        """
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


class KeyController:
    """
    Listens for keys and performs actions on them.
    """

    def __init__(
        self,
        stdin: asyncio.StreamReader,
        canonical_mode_disabler: CanonicalModeDisabler,
    ) -> None:
        """
        :param stdin: Stdin stream.
        :param canonical_mode_disabler: Disabler of canonical mode in the terminal.
        """
        self._stdin = stdin
        self._canonical_mode_disabler = canonical_mode_disabler

    async def run(self, shutdown_event: asyncio.Event) -> None:
        """
        Listen for keys and perform actions on them.

        :param shutdown_event: Event to set when shutdown is requested.
        """
        with self._canonical_mode_disabler:
            while True:
                match await self._stdin.read(1):
                    case self.SHUTDOWN_TRIGGER:
                        print("\nShutting down...")
                        shutdown_event.set()
                        return
                    case self.CLEAR_SCREEN_TRIGGER:
                        print(self.CLEAR_SCREEN_ESCAPE_CODES, end="", flush=True)

    SHUTDOWN_TRIGGER = b"\x04"  # CTRL+D

    CLEAR_SCREEN_TRIGGER = b"\x0c"  # CTRL+L
    CLEAR_SCREEN_ESCAPE_CODES = "\033[H\033[J"  # move cursor to top left + clear screen

    @staticmethod
    async def create() -> KeyController:
        """
        Create an instance of KeyController for stdin/stdout.

        :return: Created instance.
        """
        stdin, _ = await aioconsole.get_standard_streams()
        stdin_fd = sys.stdin.fileno()
        return KeyController(
            stdin=stdin,
            canonical_mode_disabler=CanonicalModeDisabler(stdin_fd=stdin_fd),
        )


class Stringifier(Protocol[T_contravariant]):
    """
    Converts things to strings.
    """

    def run(self, thing: T_contravariant) -> str:
        """
        Convert a thing to a string.

        :param thing: Thing to convert.
        :return: String representation of the thing.
        """


class FetchErrorStringifier(Protocol[FE_contravariant]):
    """
    Converts fetch errors to strings.
    """

    def run(self, error: FE_contravariant) -> str:
        """
        Convert a fetch error to a string.

        :param error: Fetch error to convert.
        :return: String representation of the error.
        """


class BasicFetchErrorStringifier(FetchErrorStringifier[BasicFetchError]):
    """
    Converts basic fetch errors to strings.
    """

    def run(self, error: BasicFetchError) -> str:
        return error.message


class LoggingActionExecutor(ActionExecutor[T]):
    """
    Logs operations over things as text.
    """

    def __init__(
        self,
        data_source: str,
        stringifier: Stringifier[T],
        logger: Logger,
    ) -> None:
        """
        :param data_source: Name of the data source to fetch from.
        :param stringifier: Stringifier to use to convert things to strings.
        :param logger: Logger to use.
        """
        self._data_source = data_source
        self._stringifier = stringifier
        self._logger = logger

    async def run(self, operations: dict[Thing.Id, Operation[T]]) -> None:
        timestamp = datetime.now().isoformat(sep=" ", timespec="seconds")
        await self._logger.info(
            f"{self.GREEN}Changes for {self._data_source} [{timestamp}]{self.RESET}"
        )

        create_operations: dict[Thing.Id, CreateOperation] = {
            k: v for k, v in operations.items() if isinstance(v, CreateOperation)
        }
        delete_operations: dict[Thing.Id, DeleteOperation] = {
            k: v for k, v in operations.items() if isinstance(v, DeleteOperation)
        }
        update_operations: dict[Thing.Id, UpdateOperation] = {
            k: v for k, v in operations.items() if isinstance(v, UpdateOperation)
        }

        if len(create_operations) > 0:
            await self._logger.info(f"{self.YELLOW}Created:{self.RESET}")
            for id_, create_operation in create_operations.items():
                await self._logger.info(
                    f"* {id_}\n" f"  {self._stringifier.run(create_operation.item)}"
                )
        if len(delete_operations) > 0:
            await self._logger.info(f"{self.YELLOW}Deleted:{self.RESET}")
            for id_, delete_operation in delete_operations.items():
                await self._logger.info(
                    f"* {id_}\n" f"  {self._stringifier.run(delete_operation.item)}"
                )
        if len(update_operations) > 0:
            await self._logger.info(f"{self.YELLOW}Updated:{self.RESET}")
            for id_, update_operation in update_operations.items():
                await self._logger.info(
                    f"* {id_}\n"
                    f"  from: {self._stringifier.run(update_operation.before)}\n"
                    f"  to:   {self._stringifier.run(update_operation.after)}"
                )

    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    RESET = "\033[0m"


class LoggingFetchErrorHandler(FetchErrorHandler[FE]):
    """
    Logs fetch errors as text.
    """

    def __init__(
        self,
        data_source: str,
        stringifier: FetchErrorStringifier[FE],
        logger: Logger,
    ) -> None:
        """
        :param data_source: Name of the data source to fetch from.
        :param stringifier: Stringifier to use to convert errors to strings.
        :param logger: Logger to use.
        """
        self._data_source = data_source
        self._stringifier = stringifier
        self._logger = logger

    async def run(self, error: FE) -> None:
        timestamp = datetime.now().isoformat(sep=" ", timespec="seconds")
        await self._logger.error(
            f"{self.RED}Error for {self._data_source} [{timestamp}]{self.RESET}\n"
            f"{self._stringifier.run(error)}"
        )

    RED = "\033[91m"
    RESET = "\033[0m"


class SafeFetcher(Fetcher[T, BasicFetchError]):
    """
    Fetches things from a data source without raising exceptions.
    """

    def __init__(self, base: Fetcher[T, BasicFetchError]) -> None:
        """
        :param base: Base data source fetcher.
        """
        self._base = base

    def get_class(self) -> type[T]:
        """
        :return: Type of things fetched by this fetcher.
        """
        return self._base.get_class()

    async def run(self) -> dict[Thing.Id, T] | BasicFetchError:
        """
        Fetches data from the data source.

        :return: Things fetched from the data source or an error.
        """
        try:
            return await self._base.run()
        except Exception:
            return BasicFetchError(message=traceback.format_exc())


class CliDeployer:
    """
    Deploys a CLI environment with meerkats that report changes to stdout.
    """

    def __init__(
        self,
        meerkats: list[Meerkat],
        key_controller: KeyController,
    ) -> None:
        """
        :param meerkats: Meerkats to run.
        :param clear_screen_listener: Key listener for clearing terminal screen.
        """
        self._meerkats = meerkats
        self._key_controller = key_controller

    async def run(self) -> None:
        """
        Deploy the configured CLI environment.
        """
        shutdown_event = asyncio.Event()
        await asyncio.gather(
            *[meerkat.run(end_event=shutdown_event) for meerkat in self._meerkats],
            self._key_controller.run(shutdown_event=shutdown_event),
        )

    @dataclass
    class MeerkatSpec(Generic[T]):
        """
        Specification of a meerkat to run.
        """

        fetcher: Fetcher[T, BasicFetchError]
        """
        Fetcher for the data source.
        """
        stringifier: Stringifier[T]
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
            name of the data source each meerkat monitors.
        :return: Created instance.
        """
        logger = Logger.with_default_handlers(name="meerkat")

        meerkats = []
        for data_source, spec in meerkat_specs.items():
            meerkat: Meerkat = Meerkat(
                fetcher=SafeFetcher(base=spec.fetcher),
                fetch_error_handler=LoggingFetchErrorHandler(
                    data_source=data_source,
                    stringifier=BasicFetchErrorStringifier(),
                    logger=logger,
                ),
                snapshot_manager=await JsonSnapshotManager.create(
                    class_=spec.fetcher.get_class(),
                    path=spec.snapshot_path,
                ),
                action_executor=LoggingActionExecutor(
                    data_source=data_source,
                    stringifier=spec.stringifier,
                    logger=logger,
                ),
                interval_manager=FixedTimeIntervalManager(
                    interval_seconds=spec.interval_seconds
                ),
            )
            meerkats.append(meerkat)

        key_controller = await KeyController.create()

        return CliDeployer(
            meerkats=meerkats,
            key_controller=key_controller,
        )
