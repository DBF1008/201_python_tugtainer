import logging
from typing import Final

from sqlalchemy import select

from backend.core.action_result import (
    HostActionResult,
)
from backend.core.agent_client import AgentClientManager
from backend.core.notifications_core import send_check_notification
from backend.core.progress.progress_cache import ProgressCache
from backend.core.progress.progress_schemas import (
    AllActionProgress,
)
from backend.core.progress.progress_util import (
    ALL_CONTAINERS_STATUS_KEY,
    acquire_action_lock,
    release_action_lock,
)
from backend.db.session import async_session_maker
from backend.enums.action_status_enum import EActionStatus
from backend.modules.hosts.hosts_model import HostsModel

from .check_host_containers import check_host_containers


async def check_all_containers(
    manual: bool = False,
    cache_key: str | None = None,
) -> None:
    """
    Check all containers of all hosts
    :param manual: manual check includes all containers
    :param cache_key: task-instance progress id to report under. When omitted
        (scheduled call) the stable "all" key is used.
    """
    progress_key: Final = cache_key or ALL_CONTAINERS_STATUS_KEY
    cache: Final = ProgressCache[AllActionProgress](progress_key)
    logger: Final = logging.getLogger("check_all_containers")

    if not acquire_action_lock(ALL_CONTAINERS_STATUS_KEY):
        logger.warning("Check process is already running. Exiting.")
        cache.set({"status": EActionStatus.DONE})
        return

    try:
        cache.set(
            {"status": EActionStatus.PREPARING},
        )
        logger.info("Start checking of all containers for all hosts")

        async with async_session_maker() as session:
            hosts: Final = (
                (await session.execute(select(HostsModel).where(HostsModel.enabled)))
                .scalars()
                .all()
            )

        cache.update(
            {"status": EActionStatus.CHECKING},
        )
        results: list[HostActionResult] = []
        for host in hosts:
            try:
                client = AgentClientManager.get_host_client(host)
                result = await check_host_containers(host, client, manual)
                if result:
                    results += [result]
            except Exception:
                logger.exception(f"Failed to check host {host.name}")

        cache.update(
            {
                "status": EActionStatus.DONE,
                "result": {item.host_id: item for item in results if item},
            }
        )
        try:
            await send_check_notification(results)
        except Exception:
            logger.exception("Failed to send notification")

    except Exception:
        cache.update({"status": EActionStatus.ERROR})
        logger.exception("Error while checking all containers for all hosts")
    finally:
        release_action_lock(ALL_CONTAINERS_STATUS_KEY)
