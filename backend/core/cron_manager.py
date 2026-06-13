import logging
from collections.abc import Callable
from zoneinfo import ZoneInfo, available_timezones

import aiocron

from backend.core.check_actions.check_all_containers import check_all_containers
from backend.core.update_actions.update_all_containers import update_all_containers
from backend.enums.cron_jobs_enum import ECronJob
from backend.modules.settings.settings_enum import ESettingKey
from backend.modules.settings.settings_storage import SettingsStorage

VALID_TIMEZONES = available_timezones()

# Single source of truth tying each automatic job to the crontab setting that
# drives it. Automatic check/update are optional and disabled by default (see
# README), so an unset crontab means the job is intentionally absent -- it is
# NOT a scheduler fault. Used both to schedule jobs and to tell an idle
# scheduler apart from a broken one.
JOB_CRONTAB_SETTINGS: dict[ECronJob, ESettingKey] = {
    ECronJob.CHECK_CONTAINERS: ESettingKey.CHECK_CRONTAB_EXPR,
    ECronJob.UPDATE_CONTAINERS: ESettingKey.UPDATE_CRONTAB_EXPR,
}


async def schedule_actions_on_init():
    """
    Schedule container check and update on app init.

    Only jobs whose crontab is configured get scheduled; the rest stay
    unscheduled on purpose (manual-only mode).
    """
    tz = SettingsStorage.get(ESettingKey.TIMEZONE)
    job_funcs: dict[ECronJob, Callable] = {
        ECronJob.CHECK_CONTAINERS: check_all_containers,
        ECronJob.UPDATE_CONTAINERS: update_all_containers,
    }

    for job, setting_key in JOB_CRONTAB_SETTINGS.items():
        crontab = SettingsStorage.get(setting_key)
        if crontab:
            CronManager.schedule_job(job, crontab, tz, job_funcs[job])


class CronManager:
    _instance = None
    _jobs: dict[str, aiocron.Cron] = {}

    def __new__(cls, *args, **kwargs):
        # Singleton
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    def schedule_job(
        cls,
        name: str,
        cron_expr: str,
        tz: str | None,
        func: Callable,
        *args,
        **kwargs,
    ):
        """
        Create or recreate cron job.
        :param name: unique name
        :param cron_expr: crontab str e.g. '*/5 * * * *'
        :param func: coroutine
        """
        cls.cancel_job(name)
        _tz = ZoneInfo(tz) if tz in VALID_TIMEZONES else None
        cls._jobs[name] = aiocron.crontab(
            cron_expr, func=func, args=args, kwargs=kwargs, tz=_tz
        )
        logging.info(
            f"[CronManager] Job '{name}' scheduled with '{cron_expr}'"
        )

    @classmethod
    def cancel_job(cls, name: str):
        """Cancel job by name"""
        if name in cls._jobs:
            cls._jobs[name].stop()
            del cls._jobs[name]
            logging.info(f"[CronManager] Job '{name}' canceled.")

    @classmethod
    def cancel_all(cls):
        """Cancel all jobs"""
        for job in list(cls._jobs.keys()):
            cls._jobs[job].stop()
        cls._jobs.clear()
        logging.info("[CronManager] All jobs canceled.")

    @classmethod
    def get_jobs(cls):
        """Get registered jobs."""
        return list(cls._jobs.keys())


def get_scheduler_status() -> dict:
    """
    Report scheduler health independently of service availability.

    A job is only *expected* when its crontab is configured. This keeps an
    intentionally idle scheduler (no automatic tasks configured -- the
    default) apart from a genuine anomaly (a configured job that is not
    actually running), so health probes are never tied to whether automatic
    tasks are enabled.

    Returns a dict with:
      - ``healthy``: ``False`` only when a configured job is missing.
      - ``scheduled_jobs``: jobs currently registered in the scheduler.
      - ``expected_jobs``: jobs that should run given the configured crontabs.
      - ``missing_jobs``: configured jobs that are not running (the anomaly).
    """
    registered = set(CronManager.get_jobs())
    expected = {
        job
        for job, setting_key in JOB_CRONTAB_SETTINGS.items()
        if SettingsStorage.get(setting_key)
    }
    missing = expected - registered
    return {
        "healthy": not missing,
        "scheduled_jobs": sorted(str(job) for job in registered),
        "expected_jobs": sorted(str(job) for job in expected),
        "missing_jobs": sorted(str(job) for job in missing),
    }
