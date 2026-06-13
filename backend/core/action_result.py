from dataclasses import dataclass, field
from typing import Literal

from python_on_whales.components.container.models import (
    ContainerInspectResult,
)
from python_on_whales.components.image.models import (
    ImageInspectResult,
)

from backend.enums.host_action_status_enum import EHostActionStatus

ContainerCheckResultType = Literal[
    "not_available",
    "available",
    "available(notified)",
    "updated",
    "rolled_back",
    "failed",
    None,
]


@dataclass
class ContainerActionResult:
    container: ContainerInspectResult
    result: ContainerCheckResultType | None = None
    image_spec: str | None = None
    local_image: ImageInspectResult | None = None
    remote_image: ImageInspectResult | None = None
    local_digests: list[str] = field(default_factory=list)
    remote_digests: list[str] = field(default_factory=list)


@dataclass
class UpdatePlanResult:
    host_id: int
    host_name: str
    items: list[ContainerActionResult] = field(default_factory=list)


@dataclass
class HostActionResult(UpdatePlanResult):
    prune_result: str | None = None
    # Terminal outcome of the host action. Lets consumers (progress cache,
    # notifications, frontend) tell apart success / skipped / failed instead
    # of an empty result silently looking like "nothing to do".
    status: EHostActionStatus = EHostActionStatus.SUCCESS
    error: str | None = None
