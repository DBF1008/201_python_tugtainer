import logging
from typing import Final

from python_on_whales.components.container.models import (
    ContainerInspectResult,
)

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
from backend.core.update_actions.update_actions_executor import (
    execute_update_plan,
)
from backend.core.update_actions.update_actions_plan import (
    build_update_plan,
)
from backend.enums.action_status_enum import EActionStatus
from backend.modules.hosts.hosts_model import HostsModel
from shared.schemas.container_schemas import (
    GetContainerListBodySchema,
)
from shared.schemas.image_schemas import PruneImagesRequestBodySchema


async def update_host_containers(
    host: HostsModel,
    client: AgentClient,
    manual: bool = False,
    cache_key: str | None = None,
) -> HostActionResult | None:
    """
    Update containers of specified host.
    :param host: host info from db
    :param client: host's docker client
    :param manual: manual update includes all containers
    :param cache_key: task-instance progress id to report under. When omitted
        (scheduled/all call) the stable host key is used.
    """
    result: Final = HostActionResult(host_id=host.id, host_name=host.name)
    lock_key: Final = get_host_cache_key(host)
    progress_key: Final = cache_key or lock_key
    cache: Final = ProgressCache[HostActionProgress](progress_key)
    logger: Final = logging.getLogger(f"update_host_containers.{host.id}:{host.name}")

    if not acquire_action_lock(lock_key):
        logger.warning("Update already running. Exiting.")
        cache.set({"status": EActionStatus.DONE})
        return None

    try:
        cache.set(
            {"status": EActionStatus.PREPARING},
        )
        logger.info("Starting update")

        try:
            docker_version = await client.common.version()
        except Exception:
            logger.exception("Failed to get docker version")
            docker_version = None

        containers: list[ContainerInspectResult] = await client.container.list(
            GetContainerListBodySchema(all=True)
        )
        manual_for = containers if manual else []

        plan = await build_update_plan(host, containers, manual_for)

        cache.update(
            {"status": EActionStatus.UPDATING},
        )

        plan_res = await execute_update_plan(
            client, host, containers, plan, docker_version
        )

        if plan_res:
            result.items.extend(plan_res.items)

        if host.prune:
            cache.update({"status": EActionStatus.PRUNING})
            logger.info("Pruning images...")
            try:
                result.prune_result = await client.image.prune(
                    PruneImagesRequestBodySchema(all=host.prune_all)
                )
            except Exception:
                logger.exception("Failed to prune images")

        cache.update({"status": EActionStatus.DONE, "result": result})
        logger.info("Update completed")
        return result
    except Exception:
        logger.exception("Failed to update")
        cache.update(
            {"status": EActionStatus.ERROR},
        )
        return None
    finally:
        release_action_lock(lock_key)
