"""Structured JSON logging with rotation.

Three separate destinations, because they answer different questions:

* app.log   -- everything the application does
* api.log   -- only the "compolog.api" logger tree (eBay, DHL). Keeping the raw
               request/response traffic apart means you can crank it to DEBUG
               during an integration problem without drowning the rest.
* console   -- human-readable, development only
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import sys
from datetime import UTC, datetime
from typing import Any

from app.config import settings

# Attributes LogRecord always carries; anything else was passed as `extra=` and
# is worth putting into the JSON payload.
_RESERVED = {
    "args", "asctime", "created", "exc_info", "exc_text", "filename", "funcName",
    "levelname", "levelno", "lineno", "module", "msecs", "message", "msg", "name",
    "pathname", "process", "processName", "relativeCreated", "stack_info",
    "thread", "threadName", "taskName",
}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                try:
                    json.dumps(value)
                    payload[key] = value
                except (TypeError, ValueError):
                    payload[key] = repr(value)
        return json.dumps(payload, ensure_ascii=False)


def _rotating(filename: str, formatter: logging.Formatter, level: int
              ) -> logging.Handler:
    handler = logging.handlers.RotatingFileHandler(
        settings.log_dir / filename,
        maxBytes=settings.log_rotate_mb * 1024 * 1024,
        backupCount=settings.log_backup_count,
        encoding="utf-8",
    )
    handler.setFormatter(formatter)
    handler.setLevel(level)
    return handler


def setup_logging() -> None:
    settings.ensure_directories()
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    formatter: logging.Formatter = (
        JsonFormatter() if settings.log_json
        else logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    )

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()
    root.addHandler(_rotating("app.log", formatter, level))

    if settings.debug:
        console = logging.StreamHandler(sys.stdout)
        console.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
        )
        console.setLevel(level)
        root.addHandler(console)

    # API traffic goes to its own file and does NOT propagate into app.log.
    api_logger = logging.getLogger("compolog.api")
    api_logger.handlers.clear()
    api_logger.addHandler(_rotating("api.log", JsonFormatter(), logging.DEBUG))
    api_logger.setLevel(logging.DEBUG)
    api_logger.propagate = False

    # Third-party noise.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"compolog.{name}")
