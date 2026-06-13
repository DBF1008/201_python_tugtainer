from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from pytest_mock import MockerFixture

from backend.app import app
from backend.db.session import get_async_session
from backend.enums.cron_jobs_enum import ECronJob
from backend.modules.settings.settings_enum import ESettingKey

module_path = "backend.modules.public.public_router"
cron_module_path = "backend.core.cron_manager"

client = TestClient(app)


@pytest.fixture(autouse=True)
def _clear_dependency_overrides():
    """Keep tests isolated: drop any dependency overrides after each test."""
    yield
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


def _override_session(mocker: MockerFixture, execute):
    """Point /public/health at a fake session with the given execute behaviour."""
    fake_session = mocker.Mock()
    fake_session.execute = execute

    async def fake_get_async_session():
        yield fake_session

    app.dependency_overrides[get_async_session] = fake_get_async_session


def test_health_ok_without_cron_jobs(mocker: MockerFixture):
    """
    Regression: a usable instance with no scheduled jobs (manual-only mode or
    freshly initialised) must report healthy. Availability is database-only and
    must not be tied to whether automatic check/update are configured.
    """
    _override_session(
        mocker, mocker.AsyncMock(return_value=mocker.Mock())
    )

    response = client.get("/public/health")

    assert response.status_code == 200
    assert response.json() == "OK"


def test_health_returns_503_on_database_error(mocker: MockerFixture):
    _override_session(
        mocker, mocker.AsyncMock(side_effect=Exception("db down"))
    )

    response = client.get("/public/health")

    assert response.status_code == 503


def test_scheduler_healthy_when_nothing_configured(mocker: MockerFixture):
    mocker.patch(f"{cron_module_path}.CronManager.get_jobs", return_value=[])
    mocker.patch(
        f"{cron_module_path}.SettingsStorage.get", side_effect=lambda key: ""
    )

    response = client.get("/public/scheduler")

    assert response.status_code == 200
    assert response.json() == {
        "healthy": True,
        "scheduled_jobs": [],
        "expected_jobs": [],
        "missing_jobs": [],
    }


def test_scheduler_reports_anomaly_when_configured_job_missing(
    mocker: MockerFixture,
):
    crontabs = {
        ESettingKey.CHECK_CRONTAB_EXPR: "*/5 * * * *",
        ESettingKey.UPDATE_CRONTAB_EXPR: "",
    }
    mocker.patch(f"{cron_module_path}.CronManager.get_jobs", return_value=[])
    mocker.patch(
        f"{cron_module_path}.SettingsStorage.get",
        side_effect=lambda key: crontabs.get(key, ""),
    )

    response = client.get("/public/scheduler")

    assert response.status_code == 200
    data = response.json()
    assert data["healthy"] is False
    assert data["expected_jobs"] == [ECronJob.CHECK_CONTAINERS.value]
    assert data["missing_jobs"] == [ECronJob.CHECK_CONTAINERS.value]
    assert data["scheduled_jobs"] == []


def test_scheduler_healthy_when_configured_job_running(mocker: MockerFixture):
    crontabs = {
        ESettingKey.CHECK_CRONTAB_EXPR: "*/5 * * * *",
        ESettingKey.UPDATE_CRONTAB_EXPR: "",
    }
    mocker.patch(
        f"{cron_module_path}.CronManager.get_jobs",
        return_value=[ECronJob.CHECK_CONTAINERS],
    )
    mocker.patch(
        f"{cron_module_path}.SettingsStorage.get",
        side_effect=lambda key: crontabs.get(key, ""),
    )

    response = client.get("/public/scheduler")

    assert response.status_code == 200
    data = response.json()
    assert data["healthy"] is True
    assert data["missing_jobs"] == []
    assert data["scheduled_jobs"] == [ECronJob.CHECK_CONTAINERS.value]
