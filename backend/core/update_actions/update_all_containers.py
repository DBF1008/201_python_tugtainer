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
    is_allowed_start_cache,
)
from backend.db.session import async_session_maker
from backend.enums.action_status_enum import EActionStatus
from backend.enums.host_action_status_enum import EHostActionStatus
from backend.modules.hosts.hosts_model import HostsModel

from .update_host_containers import update_host_containers


async def update_all_containers():
    """
    Main func for scheduled/manual update of all containers
    marked for it, for all specified docker hosts.
    Should not raises errors, only logging.
    """
    logger: Final = logging.getLogger("update_all_containers")
    cache: Final = ProgressCache[AllActionProgress](
        ALL_CONTAINERS_STATUS_KEY
    )
    state: Final = cache.get()

    if not is_allowed_start_cache(state):
        logger.warning("Update process is already running.")
        return

    try:
        cache.set(
            {"status": EActionStatus.PREPARING},
        )
        logger.info("Start updating of all containers for all hosts")

        async with async_session_maker() as session:
            hosts: Final = (
                (
                    await session.execute(
                        select(HostsModel).where(
                            HostsModel.enabled
                        )
                    )
                )
                .scalars()
                .all()
            )

        cache.update({"status": EActionStatus.UPDATING})
        results: list[HostActionResult] = []
        for host in hosts:
            try:
                client = AgentClientManager.get_host_client(host)
                result = await update_host_containers(
                    host,
                    client,
                )
            except Exception as exc:
                logger.exception(
                    f"Failed to update containers of {host.name}"
                )
                result = HostActionResult(
                    host_id=host.id,
                    host_name=host.name,
                    status=EHostActionStatus.FAILED,
                    error=str(exc),
                )
            results.append(result)

        cache.update(
            {
                "status": EActionStatus.DONE,
                "result": {
                    item.host_id: item for item in results
                },
            }
        )
        try:
            await send_check_notification(results)
        except Exception:
            logger.exception(
                "Failed to send notification after update"
            )

    except Exception:
        cache.update({"status": EActionStatus.ERROR})
        logger.exception(
            "Error while updating of all containers for all hosts"
        )
