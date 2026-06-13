
from pydantic import BaseModel, ConfigDict


class IsUpdateAvailableResponseBodySchema(BaseModel):
    is_available: bool
    release_url: str

    model_config = ConfigDict(from_attributes=True)




class TotalUpdateCountResponseBodySchema(BaseModel):
    total_updates: int


class SchedulerStatusResponseBody(BaseModel):
    """
    Scheduler observability, reported independently of service availability.

    ``healthy`` is ``False`` only when a configured job is not running; an idle
    scheduler with no automatic tasks configured stays ``healthy``.
    """

    healthy: bool
    scheduled_jobs: list[str]
    expected_jobs: list[str]
    missing_jobs: list[str]


class VersionResponseBody(BaseModel):
    """Versions schema"""

    image_version: str | None = None
