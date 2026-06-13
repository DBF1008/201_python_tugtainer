from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from pytest_mock import MockerFixture

from backend.app import app
from backend.db.session import get_async_session
from backend.exception import TugAgentClientError

module_path = "backend.modules.public.public_router"

client = TestClient(app)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "current_version, latest_version, expected_is_available, expected_release_url",
    [
        ("1.0.0", "1.1.0", True, "https://github.com/release"),
        ("1.1.0", "1.2.0", True, "https://github.com/release"),
        ("1.2.0", "1.1.0", False, "https://github.com/release"),
        ("1.2.0", "1.2.0", False, "https://github.com/release"),
    ],
)
async def test_is_update_available(
    mocker: MockerFixture,
    current_version,
    latest_version,
    expected_is_available,
    expected_release_url,
):
    # clear cache
    from backend.modules.public.public_router import (
        is_update_available,
    )

    cast(Any, is_update_available).cache.clear()

    mocker.patch("builtins.open", mocker.mock_open(read_data=current_version))
    mocker.patch(
        f"{module_path}.fetch_latest_release",
        return_value={
            "tag_name": latest_version,
            "html_url": expected_release_url,
        },
    )

    response = client.get("/public/is_update_available")
    assert response.status_code == 200

    data = response.json()
    assert data["is_available"] == expected_is_available
    assert data["release_url"] == expected_release_url


@pytest.mark.asyncio
async def test_get_update_count(
    mocker: MockerFixture,
):
    from backend.modules.containers.containers_model import (
        ContainersModel,
    )
    from backend.modules.hosts.hosts_model import (
        HostsModel,
    )

    mocker.patch(
        f"{module_path}.Config.ENABLE_PUBLIC_API",
        True,
    )

    fake_host = HostsModel(
        id=1,
        name="host1",
        enabled=True,
        url="http://example",
        secret=None,
        ssl=True,
        timeout=5,
        container_hc_timeout=60,
        prune=False,
        prune_all=False,
    )
    fake_container_db = ContainersModel(
        host_id=1,
        name="container1",
        check_enabled=False,
        update_enabled=False,
        update_available=True,
        image_id=None,
    )

    fake_session = mocker.Mock()

    async def fake_execute(statement):
        stmt_text = str(statement).lower()
        result = mocker.Mock()
        result.scalars.return_value = result
        if "from hosts" in stmt_text:
            result.all.return_value = [fake_host]
            return result
        if "from containers" in stmt_text:
            result.all.return_value = [fake_container_db]
            return result
        raise AssertionError(f"Unexpected statement: {stmt_text}")

    fake_session.execute = mocker.AsyncMock(side_effect=fake_execute)

    async def fake_get_async_session():
        yield fake_session

    app.dependency_overrides[get_async_session] = fake_get_async_session

    fake_client = mocker.Mock()
    fake_container = mocker.Mock()
    fake_container.name = "container1"
    fake_client.container.list = mocker.AsyncMock(return_value=[fake_container])
    mocker.patch(
        f"{module_path}.AgentClientManager.get_host_client",
        return_value=fake_client,
    )

    response = client.get("/public/update_count")
    assert response.status_code == 200
    assert response.json() == {"total_updates": 1, "errors": []}


@pytest.mark.asyncio
async def test_get_update_count_degrades_on_host_error(
    mocker: MockerFixture,
):
    """A single unreachable host must not fail the whole update_count call.

    The total reflects only the reachable host, and the failing host is
    reported in the structured ``errors`` list.
    """
    from backend.modules.containers.containers_model import (
        ContainersModel,
    )
    from backend.modules.hosts.hosts_model import (
        HostsModel,
    )

    mocker.patch(
        f"{module_path}.Config.ENABLE_PUBLIC_API",
        True,
    )

    healthy_host = HostsModel(
        id=1,
        name="host1",
        enabled=True,
        url="http://h1",
        secret=None,
        ssl=True,
        timeout=5,
        container_hc_timeout=60,
        prune=False,
        prune_all=False,
    )
    failing_host = HostsModel(
        id=2,
        name="host2",
        enabled=True,
        url="http://h2",
        secret=None,
        ssl=True,
        timeout=5,
        container_hc_timeout=60,
        prune=False,
        prune_all=False,
    )
    healthy_container_db = ContainersModel(
        host_id=1,
        name="container1",
        check_enabled=False,
        update_enabled=False,
        update_available=True,
        image_id=None,
    )

    fake_session = mocker.Mock()

    async def fake_execute(statement):
        stmt_text = str(statement).lower()
        result = mocker.Mock()
        result.scalars.return_value = result
        if "from hosts" in stmt_text:
            result.all.return_value = [healthy_host, failing_host]
            return result
        if "from containers" in stmt_text:
            result.all.return_value = [healthy_container_db]
            return result
        raise AssertionError(f"Unexpected statement: {stmt_text}")

    fake_session.execute = mocker.AsyncMock(side_effect=fake_execute)

    async def fake_get_async_session():
        yield fake_session

    app.dependency_overrides[get_async_session] = fake_get_async_session

    healthy_client = mocker.Mock()
    healthy_container = mocker.Mock()
    healthy_container.name = "container1"
    healthy_client.container.list = mocker.AsyncMock(return_value=[healthy_container])

    failing_client = mocker.Mock()
    failing_client.container.list = mocker.AsyncMock(
        side_effect=TugAgentClientError(
            "Agent timeout error", "http://h2", "POST", 408, "boom"
        )
    )

    def get_client(host):
        return healthy_client if host.id == 1 else failing_client

    mocker.patch(
        f"{module_path}.AgentClientManager.get_host_client",
        side_effect=get_client,
    )

    try:
        response = client.get("/public/update_count")
    finally:
        app.dependency_overrides.pop(get_async_session, None)

    assert response.status_code == 200
    data = response.json()
    assert data["total_updates"] == 1
    assert len(data["errors"]) == 1
    assert data["errors"][0]["host_id"] == 2
    assert data["errors"][0]["host_name"] == "host2"
    assert data["errors"][0]["error"]


@pytest.mark.asyncio
async def test_get_summary_partial_host_failure(
    mocker: MockerFixture,
):
    """A single unreachable host must not fail the whole summary call.

    The healthy host returns its (here empty) stats with ``error`` unset,
    while the failing host is returned in a degraded state with ``error`` set.
    """
    from backend.modules.hosts.hosts_model import (
        HostsModel,
    )

    mocker.patch(
        f"{module_path}.Config.ENABLE_PUBLIC_API",
        True,
    )

    healthy_host = HostsModel(
        id=1,
        name="host1",
        enabled=True,
        url="http://h1",
        secret=None,
        ssl=True,
        timeout=5,
        container_hc_timeout=60,
        prune=False,
        prune_all=False,
    )
    failing_host = HostsModel(
        id=2,
        name="host2",
        enabled=True,
        url="http://h2",
        secret=None,
        ssl=True,
        timeout=5,
        container_hc_timeout=60,
        prune=False,
        prune_all=False,
    )

    fake_session = mocker.Mock()

    async def fake_execute(statement):
        stmt_text = str(statement).lower()
        result = mocker.Mock()
        result.scalars.return_value = result
        if "from hosts" in stmt_text:
            result.all.return_value = [healthy_host, failing_host]
            return result
        if "from containers" in stmt_text:
            result.all.return_value = []
            return result
        raise AssertionError(f"Unexpected statement: {stmt_text}")

    fake_session.execute = mocker.AsyncMock(side_effect=fake_execute)

    async def fake_get_async_session():
        yield fake_session

    app.dependency_overrides[get_async_session] = fake_get_async_session

    healthy_client = mocker.Mock()
    healthy_client.container.list = mocker.AsyncMock(return_value=[])
    healthy_client.image.list = mocker.AsyncMock(return_value=[])

    failing_client = mocker.Mock()
    failing_client.container.list = mocker.AsyncMock(
        side_effect=TugAgentClientError(
            "Agent connection error", "http://h2", "POST", 502, "down"
        )
    )

    def get_client(host):
        return healthy_client if host.id == 1 else failing_client

    # get_host_summary fetches the client via public_util's reference to the
    # (shared) AgentClientManager class.
    mocker.patch(
        "backend.modules.public.public_util.AgentClientManager.get_host_client",
        side_effect=get_client,
    )

    try:
        response = client.get("/public/summary")
    finally:
        app.dependency_overrides.pop(get_async_session, None)

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    by_id = {item["host_id"]: item for item in data}

    assert by_id[1]["error"] is None
    assert by_id[1]["host_enabled"] is True
    assert by_id[1]["total_containers"] == 0

    assert by_id[2]["error"]
    assert by_id[2]["host_enabled"] is True
    assert by_id[2]["total_containers"] == 0
