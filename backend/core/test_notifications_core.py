import pytest
from pytest_mock import MockerFixture

from backend.const import DEFAULT_NOTIFICATION_TEMPLATE
from backend.core.action_result import HostActionResult
from backend.core.notifications_core import send_check_notification
from backend.enums.host_action_status_enum import EHostActionStatus

MODULE = "backend.core.notifications_core"


@pytest.mark.asyncio
async def test_default_template_renders_failed_host(mocker: MockerFixture):
    """
    A failed host (empty items) must still appear in the notification body,
    so a partial failure cannot read as overall success.
    """
    send = mocker.patch(f"{MODULE}.send_notification", mocker.AsyncMock())

    results = [
        HostActionResult(
            host_id=1,
            host_name="broken-host",
            status=EHostActionStatus.FAILED,
            error="Agent timeout error",
        ),
    ]

    await send_check_notification(
        results,
        title_template="Tugtainer",
        body_template=DEFAULT_NOTIFICATION_TEMPLATE,
        urls="json://localhost",
    )

    send.assert_awaited_once()
    # send_notification(title, body, urls=...)
    body = send.await_args.args[1]
    assert "broken-host" in body
    assert "Agent timeout error" in body
    assert "Failed" in body
