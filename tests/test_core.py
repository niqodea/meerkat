import asyncio
from dataclasses import dataclass

import pytest

from meerkat.core import (
    ActionExecutor,
    CreateOperation,
    DeleteOperation,
    Fetcher,
    FetchError,
    FetchErrorHandler,
    IntervalManager,
    Meerkat,
    Operation,
    SnapshotManager,
    Thing,
    UpdateOperation,
)


@dataclass
class DummyThing(Thing):
    value: str


@dataclass
class DummyFetchError(FetchError):
    message: str


class MockFetcher(Fetcher[DummyThing, DummyFetchError]):
    def __init__(
        self,
        outputs: asyncio.Queue[dict[DummyThing.Id, DummyThing] | DummyFetchError],
    ):
        self._outputs = outputs

    def get_class(self) -> type[DummyThing]:
        return DummyThing

    async def run(self) -> dict[DummyThing.Id, DummyThing] | DummyFetchError:
        return await self._outputs.get()


class MockFetchErrorHandler(FetchErrorHandler[DummyFetchError]):
    def __init__(self, inputs: asyncio.Queue[DummyFetchError]) -> None:
        self._inputs = inputs

    def get_class(self) -> type[DummyFetchError]:
        return DummyFetchError

    async def run(self, error: DummyFetchError) -> None:
        self._inputs.put_nowait(error)


class MockActionExecutor(ActionExecutor[DummyThing]):
    def __init__(
        self, inputs: asyncio.Queue[dict[DummyThing.Id, Operation[DummyThing]]]
    ) -> None:
        self._inputs = inputs

    async def run(self, operations: dict[DummyThing.Id, Operation[DummyThing]]) -> None:
        self._inputs.put_nowait(operations)


class FakeSnapshotManager(SnapshotManager[DummyThing]):
    def __init__(
        self,
        snapshot: dict[DummyThing.Id, DummyThing],
        outputs: asyncio.Queue[dict[DummyThing.Id, Operation[DummyThing]]],
    ) -> None:
        self._snapshot = snapshot
        self._outputs = outputs

    async def run(
        self, snapshot: dict[DummyThing.Id, DummyThing]
    ) -> dict[DummyThing.Id, Operation[DummyThing]]:
        operations: dict[DummyThing.Id, Operation[DummyThing]] = {}

        for id_ in snapshot.keys() & self._snapshot.keys():
            if snapshot[id_] != self._snapshot[id_]:
                operations[id_] = UpdateOperation(self._snapshot[id_], snapshot[id_])
            self._snapshot[id_] = snapshot[id_]
        for id_ in self._snapshot.keys() - snapshot.keys():
            operations[id_] = DeleteOperation(self._snapshot[id_])
            del self._snapshot[id_]
        for id_ in snapshot.keys() - self._snapshot.keys():
            operations[id_] = CreateOperation(snapshot[id_])
            self._snapshot[id_] = snapshot[id_]

        self._outputs.put_nowait(operations)
        return operations


class FakeIntervalManager(IntervalManager):
    def __init__(self, events: asyncio.Queue[asyncio.Event]) -> None:
        self._events = events

    async def run(self, early_stop_signal: asyncio.Future) -> None:
        event = await self._events.get()
        end_interval_signal: asyncio.Future = asyncio.create_task(event.wait())
        await asyncio.wait(
            {end_interval_signal, early_stop_signal},
            return_when=asyncio.FIRST_COMPLETED,
        )


@pytest.mark.asyncio
async def test_core() -> None:
    snapshot = {
        "1": DummyThing(value="a"),
        "2": DummyThing(value="b"),
        "3": DummyThing(value="c"),
    }

    fetch_results: list[dict[DummyThing.Id, DummyThing] | DummyFetchError] = [
        {
            "1": DummyThing(value="a"),
            "3": DummyThing(value="c"),
            "4": DummyThing(value="d"),
        },
        {
            "1": DummyThing(value="x"),
            "3": DummyThing(value="y"),
            "4": DummyThing(value="d"),
        },
        {
            "1": DummyThing(value="x"),
            "3": DummyThing(value="y"),
            "4": DummyThing(value="d"),
        },
        {"1": DummyThing(value="x")},
        DummyFetchError("abc"),
        {"1": DummyThing(value="x"), "6": DummyThing(value="f")},
    ]

    fetcher_outputs: asyncio.Queue[
        dict[DummyThing.Id, DummyThing] | DummyFetchError
    ] = asyncio.Queue()
    snapshot_manager_outputs: asyncio.Queue[
        dict[DummyThing.Id, Operation[DummyThing]]
    ] = asyncio.Queue()
    action_executor_inputs: asyncio.Queue[
        dict[DummyThing.Id, Operation[DummyThing]]
    ] = asyncio.Queue()
    fetch_error_handler_inputs: asyncio.Queue[DummyFetchError] = asyncio.Queue()
    interval_manager_events: asyncio.Queue[asyncio.Event] = asyncio.Queue()

    meerkat = Meerkat(
        fetcher=MockFetcher(fetcher_outputs),
        fetch_error_handler=MockFetchErrorHandler(fetch_error_handler_inputs),
        snapshot_manager=FakeSnapshotManager(snapshot, snapshot_manager_outputs),
        action_executor=MockActionExecutor(action_executor_inputs),
        interval_manager=FakeIntervalManager(interval_manager_events),
    )

    end_event = asyncio.Event()
    task = asyncio.create_task(meerkat.run(end_event))

    for fetch_result in fetch_results:
        fetcher_outputs.put_nowait(fetch_result)
        if isinstance(fetch_result, dict):
            snapshot_manager_output = await snapshot_manager_outputs.get()
            if len(snapshot_manager_output) > 0:
                action_executor_input = await action_executor_inputs.get()
                assert action_executor_input == snapshot_manager_output
        elif isinstance(fetch_result, DummyFetchError):
            fetch_error_handler_input = await fetch_error_handler_inputs.get()
            assert fetch_error_handler_input == fetch_result
        interval_manager_event = asyncio.Event()
        interval_manager_events.put_nowait(interval_manager_event)
        interval_manager_event.set()

    assert action_executor_inputs.empty()
    assert fetch_error_handler_inputs.empty()

    end_event.set()
    await task
