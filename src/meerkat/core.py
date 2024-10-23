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
    def get(self) -> dict[Thing.Id, T]: ...

    def overwrite(self, snapshot: dict[Thing.Id, T]) -> None: ...


class IntervalManager(Protocol):
    async def run(self) -> None: ...


# --------------------------------------------------------------------------------------
# Base implementations


class BaseTruthSourceError(TruthSourceError):
    message: str


class BaseTruthSourceErrorHandler(TruthSourceErrorHandler[BaseTruthSourceError]):
    def get_class(self) -> type[BaseTruthSourceError]:
        return BaseTruthSourceError

    async def run(self, error: BaseTruthSourceError) -> None:
        print(f"Error: {error.message}")


class BaseActionExecutor(ActionExecutor[T]):
    def __init__(
        self,
        name: str,
        stringifier: Callable[[T], str],
    ) -> None:
        self._name = name
        self._stringifier = stringifier

    async def run(self, operations: dict[Thing.Id, Operation[T]]) -> None:
        print(f"Changes for {self._name} [{datetime.now().replace(microsecond=0)}]")

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
            print("* Created:")
            for create_operation in create_operations.values():
                print(f"  * {self._stringifier(create_operation.item)}")
        if len(delete_operations) > 0:
            print("* Deleted:")
            for delete_operation in delete_operations.values():
                print(f"  * {self._stringifier(delete_operation.item)}")
        if len(update_operations) > 0:
            print("* Updated:")
            for update_operation in update_operations.values():
                print(f"  * from: {self._stringifier(update_operation.before)}")
                print(f"    to:   {self._stringifier(update_operation.after)}")


class BaseSnapshotManager(Generic[T]):
    def __init__(
        self,
        thing_class: type[T],
        path: Path,
        thing_ids: set[Thing.Id],
    ) -> None:
        self._thing_class = thing_class
        self._path = path
        self._thing_ids = thing_ids

    def get(self) -> dict[Thing.Id, T]:
        snapshot = {}
        for thing_id in self._thing_ids:
            thing_path = self._path / f"{thing_id}.json"
            thing_dict = json.loads(thing_path.read_text())
            thing = self._thing_class.from_dict(thing_dict)
            snapshot[thing_id] = thing
        return snapshot

    def overwrite(self, snapshot: dict[Thing.Id, T]) -> None:
        if not (self._path / BaseSnapshotManager.PATH_MARKER).exists():
            raise ValueError("Marker file not found")
        for thing_id in self._thing_ids:
            thing_path = self._path / f"{thing_id}.json"
            thing_path.unlink()
        for thing_id, thing in snapshot.items():
            thing_path = self._path / f"{thing_id}.json"
            thing_dict = thing.to_dict()
            thing_path.write_text(json.dumps(thing_dict))
        self._thing_ids = set(snapshot.keys())

    PATH_MARKER = ".snapshot"


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
        before_snapshot = self._snapshot_manager.get()

        truth_source_result = await self._truth_source_fetcher.run()

        if isinstance(truth_source_result, TruthSourceError):
            await self._truth_source_error_handler.run(truth_source_result)  # type: ignore[arg-type]
            return

        after_snapshot = truth_source_result

        thing_operations: dict[Thing.Id, Operation[T]] = {}
        for key in before_snapshot.keys() & after_snapshot.keys():
            if (before := before_snapshot[key]) != (after := after_snapshot[key]):
                thing_operations[key] = UpdateOperation(before, after)
        for key in before_snapshot.keys() - after_snapshot.keys():
            thing_operations[key] = DeleteOperation(before_snapshot[key])
        for key in after_snapshot.keys() - before_snapshot.keys():
            thing_operations[key] = CreateOperation(after_snapshot[key])

        if len(thing_operations) == 0:
            return

        self._snapshot_manager.overwrite(after_snapshot)
        await self._action_executor.run(thing_operations)

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
            snapshot_manager=BaseSnapshotManager(
                thing_class=truth_source_fetcher.get_class(),
                path=snapshot_path,
                thing_ids={p.stem for p in snapshot_path.glob("*.json")},
            ),
            action_executor=BaseActionExecutor(
                name=name,
                stringifier=stringifier,
            ),
            interval_manager=BaseIntervalManager(
                interval_seconds=interval_seconds,
            ),
        )
