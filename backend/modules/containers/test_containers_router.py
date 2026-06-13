from unittest.mock import AsyncMock, Mock

import pytest
from fastapi.testclient import TestClient
from pytest_mock import MockerFixture
from python_on_whales.components.container.models import (
    ContainerInspectResult,
)
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app import app
from backend.core.agent_client import (
    AgentClient,
    AgentClientContainer,
)
from backend.db.session import get_async_session
from backend.exception import TugAgentClientError
from backend.modules.auth.auth_util import is_authorized
from backend.modules.containers.containers_model import (
    ContainersModel,
)
from backend.modules.containers.containers_schemas import (
    ContainersListItem,
)

base_module = "backend.modules.containers.containers_router"

client = TestClient(app)


async def override_is_authorized():
    return True


app.dependency_overrides[is_authorized] = override_is_authorized


@pytest.mark.asyncio
async def test_get_container(mocker: MockerFixture):

    mocker.patch(
        f"{base_module}.get_host",
        mocker.AsyncMock(return_value=mocker.Mock()),
    )

    agent_client_mock = mocker.Mock(spec=AgentClient)
    agent_client_mock.container = mocker.Mock(spec=AgentClientContainer)
    agent_client_mock.container.inspect = mocker.AsyncMock(
        return_value=ContainerInspectResult(
            id="test-id",
            name="test-container",
        )
    )

    mocker.patch(
        f"{base_module}.AgentClientManager.get_host_client",
        return_value=agent_client_mock,
    )

    mocker.patch(
        f"{base_module}.ContainersListItem.from_sources",
        return_value=ContainersListItem(
            host_id=1,
            name="test-container",
            container_id="test-container-id",
            image="test:latest",
            protected=False,
            ports=None,
            status=None,
            exit_code=None,
            health=None,
        ),
    )

    result_scalar_mock = mocker.Mock(spec=ContainersModel)
    result_scalar_mock.id = 1
    result_scalar_mock.host_id = 1
    result_scalar_mock.name = "test-container"

    mock_result = mocker.Mock()
    mock_result.scalar_one_or_none.return_value = result_scalar_mock

    async_session_mock = AsyncMock(spec=AsyncSession)
    async_session_mock.execute.return_value = mock_result

    async def override_get_async_session():
        return async_session_mock

    app.dependency_overrides[get_async_session] = override_get_async_session

    response = client.get("/containers/1/test-container")

    assert response.status_code == 200
    res = response.json()
    assert res["item"]["host_id"] == 1
    assert res["item"]["name"] == "test-container"
    assert res["item"]["container_id"] == "test-container-id"
    assert res["item"]["image"] == "test:latest"


@pytest.fixture(autouse=True)
def _clear_session_override():
    """Avoid leaking a mock session override into other test modules."""
    yield
    app.dependency_overrides.pop(get_async_session, None)


def _make_agent_client(mocker: MockerFixture, inspect: AsyncMock) -> Mock:
    agent_client_mock = mocker.Mock(spec=AgentClient)
    agent_client_mock.container = mocker.Mock(spec=AgentClientContainer)
    agent_client_mock.container.inspect = inspect
    return agent_client_mock


def _override_async_session() -> AsyncMock:
    async_session_mock = AsyncMock(spec=AsyncSession)

    async def override_get_async_session():
        return async_session_mock

    app.dependency_overrides[get_async_session] = override_get_async_session
    return async_session_mock


def _patch_host(mocker: MockerFixture, *, enabled: bool) -> Mock:
    host = mocker.Mock()
    host.enabled = enabled
    mocker.patch(
        f"{base_module}.get_host",
        mocker.AsyncMock(return_value=host),
    )
    return host


@pytest.mark.asyncio
async def test_patch_container_data_persists_after_validation(mocker: MockerFixture):
    """Happy path: the db write runs once, after host/agent/container checks."""
    _patch_host(mocker, enabled=True)

    inspect_mock = mocker.AsyncMock(
        return_value=ContainerInspectResult(id="test-id", name="test-container")
    )
    mocker.patch(
        f"{base_module}.AgentClientManager.get_host_client",
        return_value=_make_agent_client(mocker, inspect_mock),
    )

    insert_mock = mocker.patch(
        f"{base_module}.insert_or_update_container",
        mocker.AsyncMock(return_value=mocker.Mock(spec=ContainersModel)),
    )

    mocker.patch(
        f"{base_module}.ContainersListItem.from_sources",
        return_value=ContainersListItem(
            host_id=1,
            name="test-container",
            container_id="test-container-id",
            image="test:latest",
            protected=False,
            ports=None,
            status=None,
            exit_code=None,
            health=None,
        ),
    )

    _override_async_session()

    response = client.patch(
        "/containers/1/test-container",
        json={"check_enabled": True},
    )

    assert response.status_code == 200
    assert response.json()["name"] == "test-container"
    inspect_mock.assert_awaited_once_with("test-container")
    insert_mock.assert_awaited_once()
    # The persisted row targets the host/container from the request path.
    args = insert_mock.await_args.args
    assert args[1] == 1  # host_id
    assert args[2] == "test-container"  # c_name


@pytest.mark.asyncio
async def test_patch_container_data_disabled_host_does_not_persist(
    mocker: MockerFixture,
):
    """A disabled host aborts the request before any db write or agent call."""
    _patch_host(mocker, enabled=False)

    inspect_mock = mocker.AsyncMock()
    mocker.patch(
        f"{base_module}.AgentClientManager.get_host_client",
        return_value=_make_agent_client(mocker, inspect_mock),
    )

    insert_mock = mocker.patch(
        f"{base_module}.insert_or_update_container",
        mocker.AsyncMock(),
    )

    _override_async_session()

    response = client.patch(
        "/containers/1/test-container",
        json={"check_enabled": True},
    )

    assert response.status_code == 409
    # No dirty data: the write was never attempted, agent never contacted.
    insert_mock.assert_not_awaited()
    inspect_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_patch_container_data_agent_error_does_not_persist(
    mocker: MockerFixture,
):
    """A failing agent inspect (missing container / timeout) writes nothing."""
    _patch_host(mocker, enabled=True)

    inspect_mock = mocker.AsyncMock(
        side_effect=TugAgentClientError(
            "Agent request error",
            "http://agent/api/container/inspect/test-container",
            "GET",
            404,
            "not found",
        )
    )
    mocker.patch(
        f"{base_module}.AgentClientManager.get_host_client",
        return_value=_make_agent_client(mocker, inspect_mock),
    )

    insert_mock = mocker.patch(
        f"{base_module}.insert_or_update_container",
        mocker.AsyncMock(),
    )

    _override_async_session()

    # Disable re-raising so the handled error surfaces as a response, not an exception.
    failing_client = TestClient(app, raise_server_exceptions=False)
    response = failing_client.patch(
        "/containers/1/test-container",
        json={"check_enabled": True},
    )

    assert response.status_code >= 400
    # Failure happened at the agent inspect step, before the db write.
    inspect_mock.assert_awaited_once_with("test-container")
    insert_mock.assert_not_awaited()
