import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from backend.core.check_actions.check_all_containers import (
    check_all_containers,
)
from backend.core.update_actions.update_all_containers import (
    update_all_containers,
)

logger: Final = logging.getLogger("all_containers_action")


class EAllContainersAction(StrEnum):
    """Kind of global (all hosts) container action."""

    CHECK = "check"
    UPDATE = "update"


@dataclass(frozen=True)
class _RunningAction:
    """The single in-flight global action and its progress cache id."""

    cache_id: str
    action: EAllContainersAction


@dataclass(frozen=True)
class StartAllActionResult:
    """Outcome of attempting to start a global check/update."""

    #: Progress cache id to monitor, or ``None`` when rejected (``conflict``).
    cache_id: str | None
    #: Action currently occupying the global slot, if any.
    running_action: EAllContainersAction | None
    #: ``True`` when attached to an already-running action of the same kind.
    coalesced: bool
    #: ``True`` when rejected because a different global action is running.
    conflict: bool


# Only one global (all hosts) action may run at a time: the per-host workers
# share per-host progress cache keys, so a concurrent check + update would
# collide on those keys and skip hosts. Each accepted run still gets its own
# per-instance ``cache_id`` so callers can track exactly that instance and a
# later run can never overwrite an earlier run's progress.
_running: _RunningAction | None = None


def get_running_action() -> _RunningAction | None:
    """Return the in-flight global action, or ``None`` if idle."""
    return _running


def _start(
    action: EAllContainersAction,
    worker: Callable[[str], Awaitable[None]],
) -> StartAllActionResult:
    """
    Start ``worker`` with a fresh per-instance cache id, or coalesce/reject
    against an in-flight global action.

    The read-and-set of ``_running`` happens without an intervening ``await``,
    so it is atomic with respect to other coroutines on the event loop.
    """
    global _running

    running = _running
    if running is not None:
        if running.action == action:
            # Same kind already running: attach the caller to that instance
            # (e.g. a double-clicked "check all" or an overlapping cron tick).
            return StartAllActionResult(
                cache_id=running.cache_id,
                running_action=running.action,
                coalesced=True,
                conflict=False,
            )
        # A different global action is running: reject to avoid progress
        # cross-talk and per-host cache collisions.
        return StartAllActionResult(
            cache_id=None,
            running_action=running.action,
            coalesced=False,
            conflict=True,
        )

    cache_id = str(uuid.uuid4())
    _running = _RunningAction(cache_id=cache_id, action=action)

    async def _runner() -> None:
        global _running
        try:
            await worker(cache_id)
        finally:
            if _running is not None and _running.cache_id == cache_id:
                _running = None

    asyncio.create_task(_runner())
    return StartAllActionResult(
        cache_id=cache_id,
        running_action=action,
        coalesced=False,
        conflict=False,
    )


def start_check_all(manual: bool = False) -> StartAllActionResult:
    """
    Start a global check of all containers on all hosts.
    :param manual: manual check includes all containers
    """
    return _start(
        EAllContainersAction.CHECK,
        lambda cache_id: check_all_containers(cache_id, manual),
    )


def start_update_all() -> StartAllActionResult:
    """Start a global update of all containers on all hosts."""
    return _start(
        EAllContainersAction.UPDATE,
        lambda cache_id: update_all_containers(cache_id),
    )


async def run_scheduled_check_all() -> None:
    """Cron entrypoint for the global check (skips when busy)."""
    result = start_check_all(manual=False)
    if result.conflict:
        logger.info(
            "Skipped scheduled check: global %s is already running",
            result.running_action,
        )
    elif result.coalesced:
        logger.info("Scheduled check attached to a running check")


async def run_scheduled_update_all() -> None:
    """Cron entrypoint for the global update (skips when busy)."""
    result = start_update_all()
    if result.conflict:
        logger.info(
            "Skipped scheduled update: global %s is already running",
            result.running_action,
        )
    elif result.coalesced:
        logger.info("Scheduled update attached to a running update")
