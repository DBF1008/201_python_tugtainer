from enum import StrEnum


class EHostActionStatus(StrEnum):
    """
    Terminal outcome of a host's check/update action.

    Distinct from EActionStatus, which describes the progress lifecycle
    (PREPARING/CHECKING/.../DONE/ERROR). This describes how the action
    ended for a single host, so consumers can tell apart a host that ran
    fine, a host that was skipped, and a host that failed.
    """

    SUCCESS = "success"
    SKIPPED = "skipped"
    FAILED = "failed"
