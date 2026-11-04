"""Celery application.

Redis is used twice:
  * as the BROKER - the queue of "please review PR #123" messages
  * as the RESULT BACKEND - where task return values are stored (handy for
    debugging, not used by the API)

Run a worker with (Windows needs `--pool=solo` because Celery's default
prefork pool does not work well there):

    celery -A app.celery_app:celery_app worker --loglevel=info --pool=solo

Linux/macOS:

    celery -A app.celery_app:celery_app worker --loglevel=info
"""

from __future__ import annotations

from celery import Celery
from celery.signals import after_setup_logger, after_setup_task_logger

from app.config import settings
from app.logging_config import configure_logging

celery_app = Celery(
    "reviewpilot",
    broker=settings.redis_url,
    backend=settings.redis_url,
    # Modules that contain @task definitions.
    include=["app.tasks.review_task"],
)

celery_app.conf.update(
    # --- serialisation -------------------------------------------------- #
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    # --- reliability ---------------------------------------------------- #
    # Acknowledge a task only AFTER it finishes: if a worker is killed mid
    # review, the job is redelivered instead of silently lost.
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    # Take one job at a time per worker process: reviews are heavy, and this
    # keeps the dashboard's "running" state honest.
    worker_prefetch_multiplier=1,
    # --- timeouts ------------------------------------------------------- #
    task_soft_time_limit=840,  # raises SoftTimeLimitExceeded inside the task
    task_time_limit=900,  # hard kill
    # --- misc ----------------------------------------------------------- #
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    result_expires=24 * 60 * 60,
    broker_connection_retry_on_startup=True,
    # Set CELERY_TASK_ALWAYS_EAGER=true to execute jobs inline (no worker).
    task_always_eager=settings.celery_task_always_eager,
    task_eager_propagates=False,
)


@after_setup_logger.connect
def _configure_worker_logging(logger=None, **kwargs) -> None:  # noqa: ANN001
    """Celery builds its own loggers; align them with ours."""
    configure_logging(settings.log_level, force=True)


@after_setup_task_logger.connect
def _configure_task_logging(logger=None, **kwargs) -> None:  # noqa: ANN001
    configure_logging(settings.log_level, force=True)
