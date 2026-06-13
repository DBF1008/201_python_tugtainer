from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from pytest_mock import MockerFixture

from backend.app import app
from backend.db.session import get_async_session

module_path = "backend.modules.public.public_router"

client = TestClient(app)


@pytest.mark.asyncio
async def test_health_no_cron_jobs(mocker: MockerFixture):
    """Test health endpoint returns healthy even when no cron jobs are scheduled.

    This is the bug fix scenario: automatic updates are disabled by default,
    so the health check should not fail when CHECK_CONTAINERS is not scheduled.
    """
    fake_session = mocker.Mock()
    fake_session.execute = mocker.AsyncMock()

    async def fake_get_async_session():
        yield fake_session

    app.dependency_overrides[get_async_session] = fake_get_async_session

    # Mock CronManager to return empty job list
    mocker.patch(
        f"{module_path}.CronManager.get_jobs",
        return_value=[],
    )

    response = client.get("/public/health")
    assert response.status_code == 200

    data = response.json()
    assert data["status"] == "healthy"
    assert data["scheduler"]["check_containers_scheduled"] is False
    assert data["scheduler"]["update_containers_scheduled"] is False

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_health_with_cron_jobs(mocker: MockerFixture):
    """Test health endpoint includes scheduler status when jobs are scheduled."""
    from backend.enums.cron_jobs_enum import ECronJob

    fake_session = mocker.Mock()
    fake_session.execute = mocker.AsyncMock()

    async def fake_get_async_session():
        yield fake_session

    app.dependency_overrides[get_async_session] = fake_get_async_session

    # Mock CronManager to return scheduled jobs
    mocker.patch(
        f"{module_path}.CronManager.get_jobs",
        return_value=[ECronJob.CHECK_CONTAINERS, ECronJob.UPDATE_CONTAINERS],
    )

    response = client.get("/public/health")
    assert response.status_code == 200

    data = response.json()
    assert data["status"] == "healthy"
    assert data["scheduler"]["check_containers_scheduled"] is True
    assert data["scheduler"]["update_containers_scheduled"] is True

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_health_database_failure(mocker: MockerFixture):
    """Test health endpoint returns 503 when database is unavailable."""
    fake_session = mocker.Mock()
    fake_session.execute = mocker.AsyncMock(side_effect=Exception("DB connection failed"))

    async def fake_get_async_session():
        yield fake_session

    app.dependency_overrides[get_async_session] = fake_get_async_session

    response = client.get("/public/health")
    assert response.status_code == 503
    assert "Database error" in response.json()["detail"]

    app.dependency_overrides.clear()


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
    assert response.json() == {"total_updates": 1}
