
from pydantic import BaseModel, ConfigDict


class HealthSchedulerStatusSchema(BaseModel):
    """Scheduler status information for health check"""

    check_containers_scheduled: bool
    update_containers_scheduled: bool


class HealthResponseBodySchema(BaseModel):
    """Health check response schema"""

    status: str
    scheduler: HealthSchedulerStatusSchema


class IsUpdateAvailableResponseBodySchema(BaseModel):
    is_available: bool
    release_url: str

    model_config = ConfigDict(from_attributes=True)




class TotalUpdateCountResponseBodySchema(BaseModel):
    total_updates: int


class VersionResponseBody(BaseModel):
    """Versions schema"""

    image_version: str | None = None
