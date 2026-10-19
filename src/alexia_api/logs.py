"""How the server writes its log.

There are two formats, one for people and one for machines. Both go to standard error, where a
process manager or a container runtime collects them. A record carries only the few fields the
server chose to log, so an operator can paste a log into a bug report without cleaning it first.
"""

import json
import logging
import time
from typing import Any, Final

from alexia_api.config import LogFormat, LogLevel

LOG_FIELDS: Final = ("request_id", "account", "key", "code")
TIME_FORMAT: Final = "%Y-%m-%dT%H:%M:%SZ"


class PlainFormatter(logging.Formatter):
    """One line with the time in UTC, the level, the logger, the message, and then `name=value`."""

    converter = staticmethod(time.gmtime)

    def __init__(self) -> None:
        super().__init__(
            "%(asctime)s %(levelname)-7s %(name)s %(message)s%(fields)s", datefmt=TIME_FORMAT
        )

    def format(self, record: logging.LogRecord) -> str:
        record.fields = "".join(
            f" {name}={value}"
            for name in LOG_FIELDS
            if (value := getattr(record, name, None)) is not None
        )
        return super().format(record)


class JsonFormatter(logging.Formatter):
    """One JSON object per line, with the same fields as the plain line."""

    converter = staticmethod(time.gmtime)

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "time": self.formatTime(record, TIME_FORMAT),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for name in LOG_FIELDS:
            value = getattr(record, name, None)
            if value is not None:
                entry[name] = value
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False)


_FORMATTERS: Final = {"text": PlainFormatter, "json": JsonFormatter}


def log_config(level: LogLevel, fmt: LogFormat) -> dict[str, Any]:
    """The logging setup for `logging.config.dictConfig`, which is also what uvicorn takes.

    The request log of the server replaces uvicorn's, because uvicorn would write the whole path
    and a path can hold a child's name. The HTTP client libraries stay at warning level, because at
    info level they write every portal address.
    """
    shown = level.upper()
    formatter = _FORMATTERS[fmt]
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {"line": {"()": f"{formatter.__module__}.{formatter.__qualname__}"}},
        "handlers": {
            "stderr": {
                "class": "logging.StreamHandler",
                "formatter": "line",
                "stream": "ext://sys.stderr",
            }
        },
        "root": {"handlers": ["stderr"], "level": "WARNING"},
        "loggers": {
            "alexia_api": {"level": shown},
            "uvicorn": {"level": shown},
            "uvicorn.access": {"handlers": [], "propagate": False},
            "httpx": {"level": "WARNING"},
            "httpcore": {"level": "WARNING"},
        },
    }
