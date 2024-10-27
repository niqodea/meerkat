from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, ClassVar, Generic, Protocol, TypeAlias, TypeVar

from dataclass_wizard import JSONWizard  # type: ignore[import-untyped]

# --------------------------------------------------------------------------------------
# Types


@dataclass
class Thing(JSONWizard):
    Id: ClassVar[TypeAlias] = str


T = TypeVar("T", bound=Thing)
T_covariant = TypeVar("T_covariant", bound=Thing, covariant=True)


@dataclass
class Operation(Generic[T]): ...


@dataclass
class CreateOperation(Operation[T]):
    item: T


@dataclass
class DeleteOperation(Operation[T]):
    item: T


@dataclass
class UpdateOperation(Operation[T]):
    before: T
    after: T


@dataclass
class TruthSourceError: ...


TSE = TypeVar("TSE", bound=TruthSourceError)
TSE_covariant = TypeVar("TSE_covariant", bound=TruthSourceError, covariant=True)

# --------------------------------------------------------------------------------------
# Protocols


class TruthSourceFetcher(Protocol[T_covariant, TSE_covariant]):
    def get_class(self) -> type[T_covariant]: ...

    async def run(self) -> dict[Thing.Id, T_covariant] | TSE_covariant: ...


class TruthSourceErrorHandler(Protocol[TSE]):
    def get_class(self) -> type[TSE]: ...

    async def run(self, error: TSE) -> None: ...


class ActionExecutor(Protocol[T]):
    async def run(self, operations: dict[Thing.Id, Operation[T]]): ...


class SnapshotManager(Protocol[T]):
    def run(self, new_snapshot: dict[Thing.Id, T]) -> dict[Thing.Id, Operation[T]]: ...


class IntervalManager(Protocol):
    async def run(self) -> None: ...


# --------------------------------------------------------------------------------------
# Base implementations


@dataclass
class BaseTruthSourceError(TruthSourceError):
    message: str


class BaseTruthSourceErrorHandler(TruthSourceErrorHandler[BaseTruthSourceError]):
    def get_class(self) -> type[BaseTruthSourceError]:
        return BaseTruthSourceError

    async def run(self, error: BaseTruthSourceError) -> None:
        print(f"{self.RED}Error: {error.message}{self.RESET}")

    RED = "\033[91m"
    RESET = "\033[0m"


class BaseActionExecutor(ActionExecutor[T]):
    def __init__(
        self,
        name: str,
        stringifier: Callable[[T], str],
    ) -> None:
        self._name = name
        self._stringifier = stringifier

    async def run(self, operations: dict[Thing.Id, Operation[T]]) -> None:
        timestamp = datetime.now().isoformat(sep=" ", timespec="seconds")
        print(f"{self.GREEN}Changes for {self._name} [{timestamp}]{self.RESET}")

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
            print(f"{self.YELLOW}* Created:{self.RESET}")
            for id_, create_operation in create_operations.items():
                print(f"  * {id_}")
                print(f"    {self._stringifier(create_operation.item)}")
        if len(delete_operations) > 0:
            print(f"{self.YELLOW}* Deleted:{self.RESET}")
            for id_, delete_operation in delete_operations.items():
                print(f"  * {id_}")
                print(f"    {self._stringifier(delete_operation.item)}")
        if len(update_operations) > 0:
            print(f"{self.YELLOW}* Updated:{self.RESET}")
            for id_, update_operation in update_operations.items():
                print(f"  * {id_}")
                print(f"    from: {self._stringifier(update_operation.before)}")
                print(f"    to:   {self._stringifier(update_operation.after)}")

    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    RESET = "\033[0m"


class BaseSnapshotManager(SnapshotManager[T]):
    def __init__(
        self,
        class_: type[T],
        path: Path,
        ids: set[Thing.Id],
    ) -> None:
        self._class = class_
        self._path = path
        self._ids = ids

    def run(self, snapshot: dict[Thing.Id, T]) -> dict[Thing.Id, Operation[T]]:
        marker_path = self._path / BaseSnapshotManager.MARKER_FILENAME
        if not marker_path.exists():
            raise ValueError("Marker file not found")
        marker_path.write_text(datetime.now().isoformat(timespec="seconds"))

        operations: dict[Thing.Id, Operation[T]] = {}

        for id_ in self._ids & snapshot.keys():
            path = self._path / f"{id_}.json"
            before = self._class.from_dict(json.loads(path.read_text()))
            after = snapshot[id_]
            if after == before:
                continue
            path.write_text(json.dumps(after.to_dict(), indent=2))
            operations[id_] = UpdateOperation(before, after)

        for id_ in self._ids - snapshot.keys():
            path = self._path / f"{id_}.json"
            object_ = self._class.from_dict(json.loads(path.read_text()))
            path.unlink()
            self._ids.remove(id_)
            operations[id_] = DeleteOperation(object_)

        for id_ in snapshot.keys() - self._ids:
            path = self._path / f"{id_}.json"
            object_ = snapshot[id_]
            path.write_text(json.dumps(object_.to_dict(), indent=2))
            self._ids.add(id_)
            operations[id_] = CreateOperation(object_)

        return operations

    MARKER_FILENAME = ".snapshot"

    @staticmethod
    def create(
        class_: type[T],
        path: Path,
    ) -> BaseSnapshotManager[T]:
        if not path.is_dir():
            raise ValueError(f"Could not find directory: {path}")

        marker_path = path / BaseSnapshotManager.MARKER_FILENAME

        if not marker_path.exists() and any(path.iterdir()):
            raise ValueError(f"Uninitialized snapshot directory is not empty: {path}")

        marker_path.touch()
        ids = {p.stem for p in path.glob("*.json")}

        return BaseSnapshotManager(
            class_=class_,
            path=path,
            ids=ids,
        )


class BaseIntervalManager(IntervalManager):
    def __init__(self, interval_seconds: int) -> None:
        self._interval_seconds = interval_seconds

    async def run(self) -> None:
        await asyncio.sleep(self._interval_seconds)


# --------------------------------------------------------------------------------------
# Core logic


class Meerkat(Generic[T, TSE_covariant]):
    def __init__(
        self,
        truth_source_fetcher: TruthSourceFetcher[T, TSE_covariant],
        truth_source_error_handler: TruthSourceErrorHandler[TSE_covariant],
        snapshot_manager: SnapshotManager[T],
        action_executor: ActionExecutor[T],
        interval_manager: IntervalManager,
    ) -> None:
        self._truth_source_fetcher = truth_source_fetcher
        self._truth_source_error_handler = truth_source_error_handler
        self._snapshot_manager = snapshot_manager
        self._action_executor = action_executor
        self._interval_manager = interval_manager

    async def run(self) -> None:
        while True:
            await self._peek()
            await self._interval_manager.run()

    async def _peek(self) -> None:
        truth_source_result = await self._truth_source_fetcher.run()

        if isinstance(truth_source_result, TruthSourceError):
            await self._truth_source_error_handler.run(truth_source_result)  # type: ignore[arg-type]
            return

        snapshot = truth_source_result
        operations = self._snapshot_manager.run(snapshot)

        if len(operations) == 0:
            return

        await self._action_executor.run(operations)

    @staticmethod
    def create(
        name: str,
        truth_source_fetcher: TruthSourceFetcher[T, BaseTruthSourceError],
        stringifier: Callable[[T], str],
        snapshot_path: Path,
        interval_seconds: int,
    ) -> Meerkat[T, BaseTruthSourceError]:
        return Meerkat(
            truth_source_fetcher=truth_source_fetcher,
            truth_source_error_handler=BaseTruthSourceErrorHandler(),
            snapshot_manager=BaseSnapshotManager.create(
                class_=truth_source_fetcher.get_class(),
                path=snapshot_path,
            ),
            action_executor=BaseActionExecutor(
                name=name,
                stringifier=stringifier,
            ),
            interval_manager=BaseIntervalManager(
                interval_seconds=interval_seconds,
            ),
        )
