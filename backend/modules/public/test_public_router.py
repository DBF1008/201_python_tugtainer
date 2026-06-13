from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from pytest_mock import MockerFixture

from backend.app import app
from backend.db.session import get_async_session

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

    mocker.patch(
        "builtins.open", mocker.mock_open(read_data=current_version)
    )
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
    fake_client.container.list = mocker.AsyncMock(
        return_value=[fake_container]
    )
    mocker.patch(
        f"{module_path}.AgentClientManager.get_host_client",
        return_value=fake_client,
    )

    response = client.get("/public/update_count")
    assert response.status_code == 200
    assert response.json() == {"total_updates": 1, "failed_hosts": []}


@pytest.mark.asyncio
async def test_get_update_count_with_failing_host(
    mocker: MockerFixture,
):
    """When one host's agent is unreachable the other host's data is still returned."""
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
        name="healthy",
        enabled=True,
        url="http://healthy",
        secret=None,
        ssl=True,
        timeout=5,
        container_hc_timeout=60,
        prune=False,
        prune_all=False,
    )
    failing_host = HostsModel(
        id=2,
        name="failing",
        enabled=True,
        url="http://failing",
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
            result.all.return_value = [healthy_host, failing_host]
            return result
        if "from containers" in stmt_text:
            result.all.return_value = [fake_container_db]
            return result
        raise AssertionError(f"Unexpected statement: {stmt_text}")

    fake_session.execute = mocker.AsyncMock(side_effect=fake_execute)

    async def fake_get_async_session():
        yield fake_session

    app.dependency_overrides[get_async_session] = fake_get_async_session

    def get_host_client(host):
        if host.id == 2:
            raise ConnectionError("agent unreachable")
        fake_client = mocker.Mock()
        fake_container = mocker.Mock()
        fake_container.name = "container1"
        fake_client.container.list = mocker.AsyncMock(
            return_value=[fake_container]
        )
        return fake_client

    mocker.patch(
        f"{module_path}.AgentClientManager.get_host_client",
        side_effect=get_host_client,
    )

    response = client.get("/public/update_count")
    assert response.status_code == 200
    data = response.json()
    assert data["total_updates"] == 1
    assert len(data["failed_hosts"]) == 1
    assert data["failed_hosts"][0]["host_id"] == 2
    assert data["failed_hosts"][0]["host_name"] == "failing"
    assert "agent unreachable" in data["failed_hosts"][0]["error"]


@pytest.mark.asyncio
async def test_get_summary_with_failing_host(
    mocker: MockerFixture,
):
    """When one host's agent is unreachable the summary endpoint still returns data for healthy hosts."""
    from backend.modules.hosts.hosts_model import (
        HostsModel,
    )

    mocker.patch(
        f"{module_path}.Config.ENABLE_PUBLIC_API",
        True,
    )

    healthy_host = HostsModel(
        id=1,
        name="healthy",
        enabled=True,
        url="http://healthy",
        secret=None,
        ssl=True,
        timeout=5,
        container_hc_timeout=60,
        prune=False,
        prune_all=False,
    )
    failing_host = HostsModel(
        id=2,
        name="failing",
        enabled=True,
        url="http://failing",
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

    # Only the healthy host's client works; the failing host raises.
    def get_host_client(host):
        if host.id == 2:
            raise ConnectionError("agent unreachable")
        fake_client = mocker.Mock()
        fake_client.container.list = mocker.AsyncMock(return_value=[])
        fake_client.image.list = mocker.AsyncMock(return_value=[])
        return fake_client

    mocker.patch(
        f"{module_path}.AgentClientManager.get_host_client",
        side_effect=get_host_client,
    )

    response = client.get("/public/summary")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2

    # Healthy host has normal data
    healthy = next(s for s in data if s["host_id"] == 1)
    assert healthy["host_name"] == "healthy"
    assert healthy["error"] is None

    # Failing host has zeroed data with error populated
    failing = next(s for s in data if s["host_id"] == 2)
    assert failing["host_name"] == "failing"
    assert failing["error"] is not None
    assert "agent unreachable" in failing["error"]
    assert failing["total_containers"] == 0
