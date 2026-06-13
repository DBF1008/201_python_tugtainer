import asyncio
from collections.abc import Callable, Coroutine
from typing import Any

import pytest

import backend.core.all_containers_action as module
from backend.core.all_containers_action import (
    EAllContainersAction,
    _start,
    get_running_action,
)


@pytest.fixture(autouse=True)
def _reset_running():
    """Isolate the module-level running-action record between tests."""
    module._running = None
    yield
    module._running = None


def _blocking_worker(
    started: asyncio.Event, release: asyncio.Event
) -> Callable[[str], Coroutine[Any, Any, None]]:
    """A worker that signals when it starts and blocks until released."""

    async def worker(cache_id: str) -> None:
        started.set()
        await release.wait()

    return worker


async def _wait_until_idle(timeout: float = 1.0) -> None:
    """Wait for the in-flight runner's ``finally`` to clear the record."""

    async def _poll() -> None:
        while get_running_action() is not None:
            await asyncio.sleep(0)

    await asyncio.wait_for(_poll(), timeout)


@pytest.mark.asyncio
async def test_start_returns_unique_id_per_run():
    started = asyncio.Event()
    release = asyncio.Event()
    first = _start(EAllContainersAction.CHECK, _blocking_worker(started, release))
    assert first.cache_id is not None
    assert first.conflict is False
    assert first.coalesced is False

    await started.wait()
    release.set()
    await _wait_until_idle()

    started2 = asyncio.Event()
    release2 = asyncio.Event()
    second = _start(EAllContainersAction.CHECK, _blocking_worker(started2, release2))
    assert second.cache_id is not None
    # A fresh instance must not reuse the previous run's slot.
    assert second.cache_id != first.cache_id

    await started2.wait()
    release2.set()
    await _wait_until_idle()


@pytest.mark.asyncio
async def test_same_kind_coalesces_onto_running_instance():
    started = asyncio.Event()
    release = asyncio.Event()
    first = _start(EAllContainersAction.CHECK, _blocking_worker(started, release))
    await started.wait()

    ran = False

    async def spy(cache_id: str) -> None:
        nonlocal ran
        ran = True

    second = _start(EAllContainersAction.CHECK, lambda _id: spy(_id))

    assert second.coalesced is True
    assert second.conflict is False
    assert second.cache_id == first.cache_id

    release.set()
    await _wait_until_idle()
    # The coalesced request must not have spawned a second worker.
    assert ran is False


@pytest.mark.asyncio
async def test_different_kind_conflicts():
    started = asyncio.Event()
    release = asyncio.Event()
    check = _start(EAllContainersAction.CHECK, _blocking_worker(started, release))
    await started.wait()

    ran = False

    async def spy(cache_id: str) -> None:
        nonlocal ran
        ran = True

    update = _start(EAllContainersAction.UPDATE, lambda _id: spy(_id))

    assert update.conflict is True
    assert update.cache_id is None
    assert update.running_action == EAllContainersAction.CHECK
    assert check.cache_id is not None

    release.set()
    await _wait_until_idle()
    assert ran is False


@pytest.mark.asyncio
async def test_record_cleared_after_completion_allows_new_run():
    started = asyncio.Event()
    release = asyncio.Event()
    first = _start(EAllContainersAction.CHECK, _blocking_worker(started, release))
    await started.wait()
    assert get_running_action() is not None

    release.set()
    await _wait_until_idle()
    assert get_running_action() is None

    # A previously-blocked different kind now starts cleanly.
    started2 = asyncio.Event()
    release2 = asyncio.Event()
    update = _start(EAllContainersAction.UPDATE, _blocking_worker(started2, release2))
    assert update.conflict is False
    assert update.cache_id is not None
    assert update.cache_id != first.cache_id

    await started2.wait()
    release2.set()
    await _wait_until_idle()
