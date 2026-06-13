import uuid

from cachetools import TTLCache
from python_on_whales.components.container.models import (
    ContainerInspectResult,
)

from backend.core.update_actions.update_actions_schema import (
    UpdatePlan,
)
from backend.modules.hosts.hosts_model import HostsModel

# Stable identity used as the running-lock key for the "all hosts" check/update
# action. It is created once (stable for the process lifetime) so that
# concurrent scheduled/manual "all" runs mutually exclude each other.
ALL_CONTAINERS_STATUS_KEY = str(uuid.uuid4())

# Running locks keyed by the *stable* action identity (host/container/plan/all).
# This guards against executing the same action twice at the same time (e.g. a
# scheduled run overlapping a manual one). The progress cache, by contrast, is
# keyed per task-instance (see ``new_progress_key``) so each watcher only ever
# reads its own run and never inherits a previous run's DONE/result.
#
# The TTL mirrors the progress cache TTL so a hung/killed task cannot hold a
# lock forever; maxsize is generous to avoid evicting a still-held lock.
_ACTION_LOCKS: TTLCache[str, bool] = TTLCache(maxsize=1024, ttl=600)


def new_progress_key() -> str:
    """
    Create a unique, task-instance-level progress identifier.

    Manual actions return this id to the client so that repeated runs of the
    same host/container/plan never share a progress cache entry (sharing one
    would leak a previous run's DONE/result into the new run, mixing progress).
    """
    return str(uuid.uuid4())


def acquire_action_lock(key: str) -> bool:
    """
    Try to mark the action identified by ``key`` as running.

    :returns: True if the lock was acquired (no other run is active for this
        identity), False if a run is already in progress.

    A successful acquire must always be paired with :func:`release_action_lock`
    in a ``finally`` block. Acquire/release are safe under the single-threaded
    asyncio loop because the check-and-set happens without an intermediate await.
    """
    if _ACTION_LOCKS.get(key):
        return False
    _ACTION_LOCKS[key] = True
    return True


def release_action_lock(key: str) -> None:
    """Release a lock previously taken with :func:`acquire_action_lock`."""
    _ACTION_LOCKS.pop(key, None)


def get_host_cache_key(host: HostsModel) -> str:
    return f"{host.id}:{host.name}"


def get_plan_cache_key(host: HostsModel, plan: UpdatePlan) -> str:
    return f"{get_host_cache_key(host)}:{sorted(plan.to_update)}"


def get_container_cache_key(host: HostsModel, container: ContainerInspectResult) -> str:
    return f"{get_host_cache_key(host)}:{container.name}"
