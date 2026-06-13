
from pydantic import BaseModel, ConfigDict


class IsUpdateAvailableResponseBodySchema(BaseModel):
    is_available: bool
    release_url: str

    model_config = ConfigDict(from_attributes=True)


class FailedHost(BaseModel):
    host_id: int
    host_name: str
    error: str


class TotalUpdateCountResponseBodySchema(BaseModel):
    total_updates: int
    failed_hosts: list[FailedHost] = []


class VersionResponseBody(BaseModel):
    """Versions schema"""

    image_version: str | None = None
