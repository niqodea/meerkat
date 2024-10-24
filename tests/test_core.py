import asyncio
from dataclasses import dataclass
from typing import Iterator

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
    def __init__(self, snapshots: Iterator[dict[str, DummyThing]]):
        self._snapshots = snapshots

    def get_class(self) -> type[DummyThing]:
        return DummyThing

    async def run(self) -> dict[str, DummyThing]:
        return next(self._snapshots)


class MockTruthSourceErrorHandler(TruthSourceErrorHandler[DummyTruthSourceError]):
    def __init__(
        self,
        futures: Iterator[asyncio.Future[DummyTruthSourceError]],
    ) -> None:
        self._futures = futures

    def get_class(self) -> type[DummyTruthSourceError]:
        return DummyTruthSourceError

    async def run(self, error: DummyTruthSourceError) -> None:
        next(self._futures).set_result(error)


class MockActionExecutor(ActionExecutor[DummyThing]):
    def __init__(
        self,
        futures: Iterator[asyncio.Future[dict[str, Operation[DummyThing]]]],
    ) -> None:
        self._futures = futures

    async def run(self, operations: dict[str, Operation[DummyThing]]) -> None:
        next(self._futures).set_result(operations)


class FakeSnapshotManager(SnapshotManager[DummyThing]):
    def __init__(self, things: dict[str, DummyThing]):
        self._things = things

    def get(self) -> dict[str, DummyThing]:
        return self._things

    def overwrite(self, things: dict[str, DummyThing]) -> None:
        self._things = things


class MockIntervalManager(IntervalManager):
    def __init__(self, events: Iterator[asyncio.Event]) -> None:
        self._events = events

    async def run(self) -> None:
        await next(self._events).wait()


@pytest.mark.asyncio
async def test_core():
    snapshot = {
        "1": DummyThing(value="a"),
        "2": DummyThing(value="b"),
        "3": DummyThing(value="c"),
    }

    truth_source_results = [
        # delete 2, create 4
        {
            "1": DummyThing(value="a"),
            "3": DummyThing(value="c"),
            "4": DummyThing(value="d"),
        },
        # update 1, 3
        {
            "1": DummyThing(value="x"),
            "3": DummyThing(value="y"),
            "4": DummyThing(value="d"),
        },
        # no changes
        {
            "1": DummyThing(value="x"),
            "3": DummyThing(value="y"),
            "4": DummyThing(value="d"),
        },
        # delete 3, 4
        {"1": DummyThing(value="x")},
        # error
        DummyTruthSourceError("abc"),
        # create 6
        {"1": DummyThing(value="x"), "6": DummyThing(value="f")},
    ]

    operations_history = [
        {
            "2": DeleteOperation(DummyThing(value="b")),
            "4": CreateOperation(DummyThing(value="d")),
        },
        {
            "1": UpdateOperation(
                before=DummyThing(value="a"),
                after=DummyThing(value="x"),
            ),
            "3": UpdateOperation(
                before=DummyThing(value="c"),
                after=DummyThing(value="y"),
            ),
        },
        {},
        {
            "3": DeleteOperation(DummyThing(value="y")),
            "4": DeleteOperation(DummyThing(value="d")),
        },
        None,
        {
            "6": CreateOperation(DummyThing(value="f")),
        },
    ]

    interval_events = [asyncio.Event() for i in range(len(truth_source_results))]

    truth_source_error_handler_futures = [
        asyncio.Future()
        for truth_source_result in truth_source_results
        if isinstance(truth_source_result, DummyTruthSourceError)
    ]
    action_executor_futures = [
        asyncio.Future()
        for operations in operations_history
        if operations is not None and len(operations) > 0
    ]

    meerkat = Meerkat(
        truth_source_fetcher=MockTruthSourceFetcher(iter(truth_source_results)),
        truth_source_error_handler=MockTruthSourceErrorHandler(
            iter(truth_source_error_handler_futures)
        ),
        snapshot_manager=FakeSnapshotManager(snapshot),
        action_executor=MockActionExecutor(iter(action_executor_futures)),
        interval_manager=MockIntervalManager(iter(interval_events)),
    )

    asyncio.create_task(meerkat.run())

    truth_source_error_handler_future_iter = iter(truth_source_error_handler_futures)
    action_executor_future_iter = iter(action_executor_futures)
    for truth_source_result, operations, interval_event in zip(
        truth_source_results, operations_history, interval_events
    ):
        if isinstance(truth_source_result, DummyTruthSourceError):
            truth_source_error_handler_input = await next(
                truth_source_error_handler_future_iter
            )
            assert truth_source_error_handler_input == truth_source_result
        elif len(operations) > 0:
            action_executor_input = await next(action_executor_future_iter)
            assert action_executor_input == operations
        interval_event.set()
