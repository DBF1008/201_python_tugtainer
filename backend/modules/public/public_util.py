import logging
from typing import Any, Final, cast

import aiohttp
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import Config
from backend.core.agent_client import AgentClientManager
from backend.modules.containers.containers_model import ContainersModel
from backend.modules.containers.containers_schemas import ContainersListItem
from backend.modules.hosts.hosts_model import HostsModel
from backend.modules.hosts.hosts_schemas import HostSummary
from shared.schemas.container_schemas import GetContainerListBodySchema
from shared.schemas.image_schemas import GetImageListBodySchema


async def fetch_latest_release() -> dict[str, Any]:
    url = "https://api.github.com/repos/quenary/tugtainer/releases/latest"
    headers: dict[str, str] = {}
    if Config.GH_TOKEN:
        headers["Authorization"] = f"Bearer {Config.GH_TOKEN}"
    async with aiohttp.ClientSession(
        headers=headers,
        timeout=aiohttp.ClientTimeout(15),
        trust_env=True,
    ) as session:
        async with session.request(
            "GET",
            url,
        ) as res:
            res.raise_for_status()
            return await res.json()


async def get_host_summary(host: HostsModel, session: AsyncSession) -> HostSummary:
    if not host.enabled:
        return HostSummary(
            host_id=host.id,
            host_name=host.name,
            host_enabled=False,
            total_containers=0,
            by_status={},
            by_health={},
            by_protected={"true": 0, "false": 0},
            by_check_enabled={"true": 0, "false": 0},
            by_update_enabled={"true": 0, "false": 0},
            by_update_available={"true": 0, "false": 0},
            total_images=0,
            unused_images=0,
            dangling_images=0,
        )

    client: Final = AgentClientManager.get_host_client(host)
    containers: Final = await client.container.list(
        GetContainerListBodySchema(all=True)
    )

    containers_db: Final = (
        (
            await session.execute(
                select(ContainersModel).where(ContainersModel.host_id == host.id)
            )
        )
        .scalars()
        .all()
    )
    containers_db_map: Final = {c.name: c for c in containers_db}

    mapped_containers: Final = [
        ContainersListItem.from_sources(
            host.id, c, containers_db_map.get(cast(str, c.name))
        )
        for c in containers
    ]

    by_status = {
        "created": 0,
        "running": 0,
        "paused": 0,
        "restarting": 0,
        "removing": 0,
        "exited": 0,
        "dead": 0,
    }
    by_health = {
        "unknown": 0,
        "healthy": 0,
        "unhealthy": 0,
        "starting": 0,
    }
    by_protected = {"true": 0, "false": 0}
    by_check_enabled = {"true": 0, "false": 0}
    by_update_enabled = {"true": 0, "false": 0}
    by_update_available = {"true": 0, "false": 0}

    for container in mapped_containers:
        if container.status:
            by_status[container.status] = by_status.get(container.status, 0) + 1

        health_key = container.health or "none"
        by_health[health_key] = by_health.get(health_key, 0) + 1

        protected_key = "true" if container.protected else "false"
        by_protected[protected_key] += 1

        if container.check_enabled is not None:
            check_key = "true" if container.check_enabled else "false"
            by_check_enabled[check_key] += 1

        if container.update_enabled is not None:
            update_key = "true" if container.update_enabled else "false"
            by_update_enabled[update_key] += 1

        if container.update_available is not None:
            avail_key = "true" if container.update_available else "false"
            by_update_available[avail_key] += 1

    images: Final = await client.image.list(GetImageListBodySchema(all=True))
    used_images: Final[set[str]] = {c.image for c in containers if c.image}

    total_images: Final = len(images)
    unused_images: int = 0
    dangling_images: int = 0

    for image in images:
        if not image.repo_tags and image.id not in used_images:
            dangling_images += 1
        if image.id not in used_images:
            unused_images += 1

    return HostSummary(
        host_id=host.id,
        host_name=host.name,
        host_enabled=True,
        total_containers=len(mapped_containers),
        by_status=by_status,
        by_health=by_health,
        by_protected=by_protected,
        by_check_enabled=by_check_enabled,
        by_update_enabled=by_update_enabled,
        by_update_available=by_update_available,
        total_images=total_images,
        unused_images=unused_images,
        dangling_images=dangling_images,
    )


def _empty_summary(host: HostsModel, error: str) -> HostSummary:
    """Return a zeroed-out summary for a host that could not be reached."""
    return HostSummary(
        host_id=host.id,
        host_name=host.name,
        host_enabled=host.enabled,
        total_containers=0,
        by_status={},
        by_health={},
        by_protected={"true": 0, "false": 0},
        by_check_enabled={"true": 0, "false": 0},
        by_update_enabled={"true": 0, "false": 0},
        by_update_available={"true": 0, "false": 0},
        total_images=0,
        unused_images=0,
        dangling_images=0,
        error=error,
    )


async def safe_get_host_summary(
    host: HostsModel, session: AsyncSession
) -> HostSummary:
    """Wrapper around ``get_host_summary`` that degrades on failure.

    If the agent for a single host is unreachable, times out, or raises any
    other exception, this function catches the error and returns a zeroed-out
    :class:`HostSummary` with the ``error`` field populated rather than
    propagating the exception and taking down the entire summary endpoint.
    """
    try:
        return await get_host_summary(host, session)
    except Exception as e:
        logging.warning(
            "Failed to get summary for host %s (id=%s): %s",
            host.name, host.id, e,
        )
        return _empty_summary(host, str(e))
