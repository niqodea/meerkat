from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime
from typing import ClassVar, Generic, Protocol, TypeAlias, TypeVar

from aiopath import Path
from dataclass_wizard import JSONWizard  # type: ignore[import-untyped]

# --------------------------------------------------------------------------------------
# Types


@dataclass
class Thing(JSONWizard):
    """
    Can be monitored by meerkat.
    """

    Id: ClassVar[TypeAlias] = str


T = TypeVar("T", bound=Thing)
T_covariant = TypeVar("T_covariant", bound=Thing, covariant=True)


@dataclass
class Operation(Generic[T]):
    """
    Represents an operation over a thing.
    """


@dataclass
class CreateOperation(Operation[T]):
    """
    Represents creation of a thing.
    """

    item: T
    """
    The craeted thing.
    """


@dataclass
class DeleteOperation(Operation[T]):
    """
    Represents deletion of a thing.
    """

    item: T
    """
    The deleted thing.
    """


@dataclass
class UpdateOperation(Operation[T]):
    """
    Represents update of a thing.
    """

    before: T
    """
    The thing before the update.
    """

    after: T
    """
    The thing after the update.
    """


@dataclass
class FetchError:
    """
    Represents a data source fetch error.
    """


FE = TypeVar("FE", bound=FetchError)
FE_contravariant = TypeVar("FE_contravariant", bound=FetchError, contravariant=True)
FE_covariant = TypeVar("FE_covariant", bound=FetchError, covariant=True)

# --------------------------------------------------------------------------------------
# Protocols


class Fetcher(Protocol[T_covariant, FE_covariant]):
    """
    Fetches things from a data source.
    """

    def get_class(self) -> type[T_covariant]:
        """
        :return: Type of things fetched by this fetcher.
        """

    async def run(self) -> dict[Thing.Id, T_covariant] | FE_covariant:
        """
        Fetches data from the data source.

        :return: Things fetched from the data source or a fetch error.
        """


class FetchErrorHandler(Protocol[FE_contravariant]):
    """
    Handles fetch errors.
    """

    async def run(self, error: FE_contravariant) -> None:
        """
        Handles a fetch error.

        :param error: Fetch error to handle.
        """


class ActionExecutor(Protocol[T]):
    """
    Executes actions in response to operations over things.
    """

    async def run(self, operations: dict[Thing.Id, Operation[T]]):
        """
        Execute an action.

        :param operations: Operations to execute the action against.
        """


class SnapshotManager(Protocol[T]):
    """
    Tracks a snapshot of things and computes operations over them.
    """

    async def run(self, snapshot: dict[Thing.Id, T]) -> dict[Thing.Id, Operation[T]]:
        """
        Track a snapshot of things and compute operations by comparison against the
        previously tracked snapshot.

        :param snapshot: Snapshot of things to track.
        :return: Operations over the things.
        """


class IntervalManager(Protocol):
    """
    Manages intervals between two subsequent runs.
    """

    async def run(self, early_stop_signal: asyncio.Future) -> None:
        """
        Run the interval.

        :param early_stop_signal: Signal to stop the interval early.
        """


# --------------------------------------------------------------------------------------
# Implementations


@dataclass
class BasicFetchError(FetchError):
    """
    Simple fetch error.
    """

    message: str
    """
    Message describing the error.
    """


class JsonSnapshotManager(SnapshotManager[T]):
    """
    Tracks a snapshot of things on disk as JSON files.
    """

    def __init__(
        self,
        class_: type[T],
        path: Path,
        ids: set[Thing.Id],
    ) -> None:
        """
        :param class_: Class of the things.
        :param path: Path to the directory where things are stored.
        :param ids: Ids of the existing things.
        """
        self._class = class_
        self._path = path
        self._ids = ids

    async def run(self, snapshot: dict[Thing.Id, T]) -> dict[Thing.Id, Operation[T]]:
        marker_path = self._path / JsonSnapshotManager.MARKER_FILENAME
        if not await marker_path.exists():
            raise ValueError("Marker file not found")
        await marker_path.write_text(datetime.now().isoformat(timespec="seconds"))

        operations: dict[Thing.Id, Operation[T]] = {}

        for id_ in self._ids & snapshot.keys():
            path = self._path / f"{id_}.json"
            before = self._class.from_dict(json.loads(await path.read_text()))
            after = snapshot[id_]
            if after == before:
                continue
            await path.write_text(json.dumps(after.to_dict(), indent=2))
            operations[id_] = UpdateOperation(before, after)

        for id_ in self._ids - snapshot.keys():
            path = self._path / f"{id_}.json"
            object_ = self._class.from_dict(json.loads(await path.read_text()))
            await path.unlink()
            self._ids.remove(id_)
            operations[id_] = DeleteOperation(object_)

        for id_ in snapshot.keys() - self._ids:
            path = self._path / f"{id_}.json"
            object_ = snapshot[id_]
            await path.write_text(json.dumps(object_.to_dict(), indent=2))
            self._ids.add(id_)
            operations[id_] = CreateOperation(object_)

        return operations

    MARKER_FILENAME = ".snapshot"

    @staticmethod
    async def create(class_: type[T], path: Path) -> JsonSnapshotManager[T]:
        """
        Create an instance of JsonSnapshotManager.

        :param class_: Class of the things.
        :param path: Path to the directory where things are stored as JSON files.
        :return: Created instance.
        """
        if not await path.is_dir():
            raise ValueError(f"Could not find directory: {path}")

        marker_path = path / JsonSnapshotManager.MARKER_FILENAME

        if not await marker_path.exists():
            # This is a hack to ensure that the directory is empty
            # Normally, we would use any(p.iterdir()), but we can't do that in async
            # any([_ async for _ in p.iterdir()]) is more readable but less performant
            async for _ in path.iterdir():
                raise ValueError(f"Initialized snapshot directory is not empty: {path}")

        await marker_path.touch()
        ids = {p.stem async for p in path.glob("*.json")}

        return JsonSnapshotManager(
            class_=class_,
            path=path,
            ids=ids,
        )


class FixedTimeIntervalManager(IntervalManager):
    """
    Manages fixed-time intervals.
    """

    def __init__(self, interval_seconds: int) -> None:
        """
        :param interval_seconds: Interval in seconds.
        """
        self._interval_seconds = interval_seconds

    async def run(self, early_stop_signal: asyncio.Future) -> None:
        end_interval_signal: asyncio.Future = asyncio.create_task(
            asyncio.sleep(self._interval_seconds)
        )
        await asyncio.wait(
            {end_interval_signal, early_stop_signal},
            return_when=asyncio.FIRST_COMPLETED,
        )


# --------------------------------------------------------------------------------------
# Core logic


class Meerkat(Generic[T, FE_covariant]):
    """
    Monitors a data source and tracks things from it, executing actions upon changes.
    """

    def __init__(
        self,
        fetcher: Fetcher[T, FE_covariant],
        fetch_error_handler: FetchErrorHandler[FE_covariant],
        snapshot_manager: SnapshotManager[T],
        action_executor: ActionExecutor[T],
        interval_manager: IntervalManager,
    ) -> None:
        """
        :param fetcher: Fetcher for the data source.
        :param fetch_error_handler: Handler for fetch errors.
        :param snapshot_manager: Tracker of fetched things and detector of changes.
        :param action_executor: Executor of actions upon changes.
        :param interval_manager: Manager for intervals between monitoring sessions.
        """
        self._fetcher = fetcher
        self._fetch_error_handler = fetch_error_handler
        self._snapshot_manager = snapshot_manager
        self._action_executor = action_executor
        self._interval_manager = interval_manager

    async def run(self, end_event: asyncio.Event) -> None:
        """
        Monitor the configured data source and track things from it, executing actions
        upon changes.

        :param end_event: Event to end the monitoring session.
        """
        end_signal: asyncio.Future = asyncio.create_task(end_event.wait())
        while not end_event.is_set():
            await self._peek()
            await self._interval_manager.run(early_stop_signal=end_signal)

    async def _peek(self) -> None:
        fetch_result = await self._fetcher.run()

        if isinstance(fetch_result, FetchError):
            await self._fetch_error_handler.run(fetch_result)  # type: ignore[arg-type]
            return

        snapshot = fetch_result
        operations = await self._snapshot_manager.run(snapshot)

        if len(operations) == 0:
            return

        await self._action_executor.run(operations)
