import asyncio
from dataclasses import dataclass

import pytest

from meerkat.core import (
    ActionExecutor,
    CreateOperation,
    DeleteOperation,
    IntervalManager,
    Meerkat,
    Operation,
    SnapshotManager,
    Thing,
    TruthSourceError,
    TruthSourceErrorHandler,
    TruthSourceFetcher,
    UpdateOperation,
)


@dataclass
class DummyThing(Thing):
    value: str


@dataclass
class DummyTruthSourceError(TruthSourceError):
    message: str


class MockTruthSourceFetcher(TruthSourceFetcher[DummyThing, DummyTruthSourceError]):
    def __init__(
        self,
        outputs: asyncio.Queue[dict[DummyThing.Id, DummyThing] | DummyTruthSourceError],
    ):
        self._outputs = outputs

    def get_class(self) -> type[DummyThing]:
        return DummyThing

    async def run(self) -> dict[DummyThing.Id, DummyThing] | DummyTruthSourceError:
        return await self._outputs.get()


class MockTruthSourceErrorHandler(TruthSourceErrorHandler[DummyTruthSourceError]):
    def __init__(self, inputs: asyncio.Queue[DummyTruthSourceError]) -> None:
        self._inputs = inputs

    def get_class(self) -> type[DummyTruthSourceError]:
        return DummyTruthSourceError

    async def run(self, error: DummyTruthSourceError) -> None:
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
    def __init__(self, signals: asyncio.Queue[None]) -> None:
        self._signals = signals

    async def run(self, early_stop_event: asyncio.Event) -> None:
        signal_task = asyncio.create_task(self._signals.get())

        async def wait_early_stop() -> None:
            await early_stop_event.wait()
            signal_task.cancel()

        early_stop_task = asyncio.create_task(wait_early_stop())

        done, pending = await asyncio.wait(
            {signal_task, early_stop_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()


@pytest.mark.asyncio
async def test_core() -> None:
    snapshot = {
        "1": DummyThing(value="a"),
        "2": DummyThing(value="b"),
        "3": DummyThing(value="c"),
    }

    truth_source_results: list[
        dict[DummyThing.Id, DummyThing] | DummyTruthSourceError
    ] = [
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
        DummyTruthSourceError("abc"),
        {"1": DummyThing(value="x"), "6": DummyThing(value="f")},
    ]

    truth_source_fetcher_outputs: asyncio.Queue[
        dict[DummyThing.Id, DummyThing] | DummyTruthSourceError
    ] = asyncio.Queue()
    snapshot_manager_outputs: asyncio.Queue[
        dict[DummyThing.Id, Operation[DummyThing]]
    ] = asyncio.Queue()
    action_executor_inputs: asyncio.Queue[
        dict[DummyThing.Id, Operation[DummyThing]]
    ] = asyncio.Queue()
    truth_source_error_handler_inputs: asyncio.Queue[DummyTruthSourceError] = (
        asyncio.Queue()
    )
    interval_manager_signals: asyncio.Queue[None] = asyncio.Queue()

    meerkat = Meerkat(
        truth_source_fetcher=MockTruthSourceFetcher(truth_source_fetcher_outputs),
        truth_source_error_handler=MockTruthSourceErrorHandler(
            truth_source_error_handler_inputs
        ),
        snapshot_manager=FakeSnapshotManager(snapshot, snapshot_manager_outputs),
        action_executor=MockActionExecutor(action_executor_inputs),
        interval_manager=FakeIntervalManager(interval_manager_signals),
    )

    end_event = asyncio.Event()
    task = asyncio.create_task(meerkat.run(end_event))

    for truth_source_result in truth_source_results:
        truth_source_fetcher_outputs.put_nowait(truth_source_result)
        if isinstance(truth_source_result, dict):
            snapshot_manager_output = await snapshot_manager_outputs.get()
            if len(snapshot_manager_output) > 0:
                action_executor_input = await action_executor_inputs.get()
                assert action_executor_input == snapshot_manager_output
        elif isinstance(truth_source_result, DummyTruthSourceError):
            truth_source_error_handler_input = (
                await truth_source_error_handler_inputs.get()
            )
            assert truth_source_error_handler_input == truth_source_result
        interval_manager_signals.put_nowait(None)

    assert action_executor_inputs.empty()
    assert truth_source_error_handler_inputs.empty()

    end_event.set()
    await task
