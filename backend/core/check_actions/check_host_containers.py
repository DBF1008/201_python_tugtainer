import logging
from typing import Final

from backend.core.action_result import (
    HostActionResult,
)
from backend.core.agent_client import AgentClient
from backend.core.progress.progress_cache import ProgressCache
from backend.core.progress.progress_schemas import (
    HostActionProgress,
)
from backend.core.progress.progress_util import (
    acquire_action_lock,
    get_host_cache_key,
    release_action_lock,
)
from backend.db.session import async_session_maker
from backend.enums.action_status_enum import EActionStatus
from backend.modules.containers.containers_util import (
    get_host_containers,
)
from backend.modules.hosts.hosts_model import HostsModel
from shared.schemas.container_schemas import (
    GetContainerListBodySchema,
)

from .check_actions_util import (
    filter_containers_by_check_enabled,
    sort_containers_by_checked_at,
)
from .check_one_container import check_one_container


async def check_host_containers(
    host: HostsModel,
    client: AgentClient,
    manual: bool = False,
    cache_key: str | None = None,
) -> HostActionResult | None:
    """
    Check all host's containers.
    :param host: host info
    :param client: host agent client
    :param manual: manual check includes all containers
    :param cache_key: task-instance progress id to report under. When omitted
        (scheduled/all call) the stable host key is used.
    """
    result: Final = HostActionResult(host_id=host.id, host_name=host.name)
    lock_key: Final = get_host_cache_key(host)
    progress_key: Final = cache_key or lock_key
    cache: Final = ProgressCache[HostActionProgress](progress_key)
    logger: Final = logging.getLogger(f"check_host_containers.{host.id}.{host.name}")

    if not acquire_action_lock(lock_key):
        logger.warning("Check action is already running. Exiting.")
        cache.set({"status": EActionStatus.DONE})
        return None

    try:
        logger.info("Starting check action")
        cache.set({"status": EActionStatus.PREPARING})
        containers = await client.container.list(GetContainerListBodySchema(all=True))
        async with async_session_maker() as session:
            containers_db: Final = await get_host_containers(
                session,
                host.id,
            )
            containers_db_map: Final = {item.name: item for item in containers_db}

        containers = filter_containers_by_check_enabled(
            containers, containers_db_map, manual
        )
        containers = sort_containers_by_checked_at(containers, containers_db_map)

        cache.update(
            {"status": EActionStatus.CHECKING},
        )
        for c in containers:
            res = await check_one_container(
                client,
                host,
                c,
            )
            result.items.append(res)

        cache.update({"status": EActionStatus.DONE, "result": result})
        return result
    except Exception:
        logger.exception("Failed to check host")
        cache.update(
            {"status": EActionStatus.ERROR},
        )
        return result
    finally:
        release_action_lock(lock_key)
