import pytest
from pytest_mock import MockerFixture

from backend.exception import TugAgentClientError
from backend.modules.hosts.hosts_model import HostsModel
from backend.modules.public.public_util import get_host_summary

util_path = "backend.modules.public.public_util"


def _make_host(*, id: int, enabled: bool) -> HostsModel:
    return HostsModel(
        id=id,
        name=f"host{id}",
        enabled=enabled,
        url=f"http://h{id}",
        secret=None,
        ssl=True,
        timeout=5,
        container_hc_timeout=60,
        prune=False,
        prune_all=False,
    )


@pytest.mark.asyncio
async def test_get_host_summary_degrades_on_agent_error(
    mocker: MockerFixture,
):
    """An unreachable agent yields a degraded summary instead of raising."""
    host = _make_host(id=1, enabled=True)

    failing_client = mocker.Mock()
    failing_client.container.list = mocker.AsyncMock(
        side_effect=TugAgentClientError(
            "Agent timeout error", "http://h1", "POST", 408, "boom"
        )
    )
    mocker.patch(
        f"{util_path}.AgentClientManager.get_host_client",
        return_value=failing_client,
    )

    # Session should not be queried once the agent call fails, but provide a
    # safe stub so any access does not blow up for the wrong reason.
    session = mocker.Mock()
    session.execute = mocker.AsyncMock()

    summary = await get_host_summary(host, session)

    assert summary.host_id == 1
    assert summary.host_enabled is True
    assert summary.total_containers == 0
    assert summary.total_images == 0
    assert summary.error is not None
    assert "Agent timeout error" in summary.error


@pytest.mark.asyncio
async def test_get_host_summary_degrades_on_unexpected_error(
    mocker: MockerFixture,
):
    """Non-agent exceptions are also contained as a degraded summary."""
    host = _make_host(id=3, enabled=True)

    failing_client = mocker.Mock()
    failing_client.container.list = mocker.AsyncMock(side_effect=RuntimeError("kaboom"))
    mocker.patch(
        f"{util_path}.AgentClientManager.get_host_client",
        return_value=failing_client,
    )

    session = mocker.Mock()
    session.execute = mocker.AsyncMock()

    summary = await get_host_summary(host, session)

    assert summary.host_enabled is True
    assert summary.error is not None
    assert "kaboom" in summary.error


@pytest.mark.asyncio
async def test_get_host_summary_disabled_host_has_no_error(
    mocker: MockerFixture,
):
    """Disabled hosts keep returning a zeroed, non-errored summary."""
    host = _make_host(id=2, enabled=False)
    session = mocker.Mock()

    summary = await get_host_summary(host, session)

    assert summary.host_enabled is False
    assert summary.error is None
    assert summary.total_containers == 0
