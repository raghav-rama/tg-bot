from __future__ import annotations

import json
import logging
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class StructuredLogMessage:
    event: str
    fields: dict[str, Any]

    def __str__(self) -> str:
        field_parts = [
            f"{key}={value}" for key, value in self.fields.items() if value is not None
        ]
        if not field_parts:
            return self.event
        return f"{self.event} " + " ".join(field_parts)


class JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        message = record.msg
        if isinstance(message, StructuredLogMessage):
            event = message.event
            fields = message.fields
        else:
            event = record.getMessage()
            fields = {}

        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(
                record.created,
                tz=timezone.utc,
            )
            .isoformat()
            .replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "event": event,
        }
        payload.update({key: value for key, value in fields.items() if value is not None})

        if record.exc_info is not None:
            exc_type, exc_value, _traceback = record.exc_info
            payload["exception_type"] = exc_type.__name__ if exc_type else None
            payload["exception_message"] = str(exc_value) if exc_value else None
            payload["exception_traceback"] = "".join(
                traceback.format_exception(*record.exc_info)
            )

        return json.dumps(payload, default=str, separators=(",", ":"))


def configure_logging(level: str, *, log_format: str = "text") -> None:
    normalized_format = log_format.strip().lower()
    formatter: logging.Formatter
    if normalized_format == "json":
        formatter = JsonLogFormatter()
    else:
        formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")

    handler = logging.StreamHandler()
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(getattr(logging, level, logging.INFO))

    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def log_kv(message: str, **fields: Any) -> StructuredLogMessage:
    return StructuredLogMessage(
        event=message,
        fields={key: value for key, value in fields.items() if value is not None},
    )
