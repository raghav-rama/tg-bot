from __future__ import annotations

import logging
from typing import Any


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def log_kv(message: str, **fields: Any) -> str:
    field_parts = [f"{key}={value}" for key, value in fields.items() if value is not None]
    if not field_parts:
        return message
    return f"{message} " + " ".join(field_parts)

