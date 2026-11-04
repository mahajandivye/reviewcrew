"""One logging configuration shared by the API process and Celery workers.

Celery is a *separate process*. If you only configure logging in main.py, the
worker's logs look different (or disappear). Configuring both from one place
is what makes `docker compose logs` / terminal output debuggable.

Every log line in this project is namespaced under the `reviewpilot` logger
tree, e.g. `reviewpilot.tasks.review_task`.
"""

from __future__ import annotations

import logging
import logging.config
import sys

_CONFIGURED = False

_LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def configure_logging(level: str = "INFO", *, force: bool = False) -> None:
    """Idempotent logging setup.

    Idempotent because both `uvicorn --reload` and Celery import modules more
    than once; adding duplicate handlers would print every line twice.
    """
    global _CONFIGURED
    if _CONFIGURED and not force:
        return

    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "default": {"format": _LOG_FORMAT, "datefmt": _DATE_FORMAT},
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "default",
                    # stdout keeps API logs in the same stream as uvicorn's.
                    "stream": sys.stdout,
                },
            },
            "loggers": {
                # Our own code: honour LOG_LEVEL.
                "reviewpilot": {
                    "handlers": ["console"],
                    "level": level.upper(),
                    "propagate": False,
                },
                # Third-party libraries: quieter, so real errors stand out.
                "uvicorn.error": {"handlers": ["console"], "level": "INFO", "propagate": False},
                "uvicorn.access": {"handlers": ["console"], "level": "WARNING", "propagate": False},
                "celery": {"handlers": ["console"], "level": "INFO", "propagate": False},
                "httpx": {"handlers": ["console"], "level": "WARNING", "propagate": False},
                "openai": {"handlers": ["console"], "level": "WARNING", "propagate": False},
            },
            "root": {"handlers": ["console"], "level": "WARNING"},
        }
    )
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """Namespaced logger helper: `get_logger(__name__)` is usually enough."""
    if not name.startswith("reviewpilot"):
        name = f"reviewpilot.{name}"
    return logging.getLogger(name)
