import pytest
from pytest_mock import MockerFixture

from backend.core.action_result import HostActionResult
from backend.core.progress import progress_cache
from backend.core.progress.progress_cache import ProgressCache
from backend.core.progress.progress_util import (
    ALL_CONTAINERS_STATUS_KEY,
)
from backend.core.update_actions.update_all_containers import (
    update_all_containers,
)
from backend.enums.action_status_enum import EActionStatus
from backend.enums.host_action_status_enum import EHostActionStatus

MODULE = "backend.core.update_actions.update_all_containers"


def _host(mocker: MockerFixture, id: int, name: str):
    # NOTE: Mock(name=...) sets the mock's repr, not a `.name` attribute,
    # so name must be assigned explicitly.
    host = mocker.Mock()
    host.id = id
    host.name = name
    return host


def _mock_session(mocker: MockerFixture, hosts: list):
    session = mocker.Mock()
    exec_result = mocker.Mock()
    exec_result.scalars.return_value.all.return_value = hosts
    session.execute = mocker.AsyncMock(return_value=exec_result)

    ctx = mocker.MagicMock()
    ctx.__aenter__ = mocker.AsyncMock(return_value=session)
    ctx.__aexit__ = mocker.AsyncMock(return_value=None)
    return ctx


@pytest.mark.asyncio
async def test_update_all_containers_reports_every_host_outcome(
    mocker: MockerFixture,
):
    """
    Regression: a host whose update fails (the inner function used to return
    None) or whose client cannot be created must stay observable in the
    progress result instead of silently disappearing.
    """
    progress_cache._CACHE.clear()

    hosts = [
        _host(mocker, 1, "ok-host"),
        _host(mocker, 2, "busy-host"),
        _host(mocker, 3, "throwing-host"),
        _host(mocker, 4, "unreachable-host"),
    ]
    mocker.patch(
        f"{MODULE}.async_session_maker",
        return_value=_mock_session(mocker, hosts),
    )

    def get_client(host):
        if host.id == 4:
            raise RuntimeError("cannot reach agent")
        return mocker.Mock()

    mocker.patch(
        f"{MODULE}.AgentClientManager.get_host_client",
        side_effect=get_client,
    )

    async def update_side_effect(host, client, manual=False):
        if host.id == 1:
            return HostActionResult(host_id=1, host_name="ok-host")
        if host.id == 2:
            return HostActionResult(
                host_id=2,
                host_name="busy-host",
                status=EHostActionStatus.SKIPPED,
            )
        raise RuntimeError("agent timeout")

    mocker.patch(
        f"{MODULE}.update_host_containers", side_effect=update_side_effect
    )
    notify = mocker.patch(
        f"{MODULE}.send_check_notification", mocker.AsyncMock()
    )

    await update_all_containers()

    state = ProgressCache(ALL_CONTAINERS_STATUS_KEY).get()
    assert state is not None
    assert state["status"] == EActionStatus.DONE
    result = state["result"]

    # No host dropped: all four outcomes are observable.
    assert set(result.keys()) == {1, 2, 3, 4}

    assert result[1].status == EHostActionStatus.SUCCESS
    assert result[1].error is None

    assert result[2].status == EHostActionStatus.SKIPPED

    # Update raised -> FAILED (previously the host vanished from results).
    assert result[3].status == EHostActionStatus.FAILED
    assert result[3].error and "agent timeout" in result[3].error

    # Client creation raised -> FAILED.
    assert result[4].status == EHostActionStatus.FAILED
    assert result[4].error and "cannot reach agent" in result[4].error

    # Notification consumer receives every host, failures included.
    notify.assert_awaited_once()
    notified = notify.await_args.args[0]
    assert {r.host_id for r in notified} == {1, 2, 3, 4}
    assert any(r.status == EHostActionStatus.FAILED for r in notified)
