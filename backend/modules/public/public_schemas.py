from pydantic import BaseModel, ConfigDict


class IsUpdateAvailableResponseBodySchema(BaseModel):
    is_available: bool
    release_url: str

    model_config = ConfigDict(from_attributes=True)


class HostErrorSchema(BaseModel):
    """Structured error for a single host that could not be reached/queried."""

    host_id: int
    host_name: str
    error: str


class TotalUpdateCountResponseBodySchema(BaseModel):
    total_updates: int
    # Hosts that failed to respond. The total above only reflects reachable
    # hosts, so callers can detect partial results via this list.
    errors: list[HostErrorSchema] = []


class VersionResponseBody(BaseModel):
    """Versions schema"""

    image_version: str | None = None
