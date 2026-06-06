from __future__ import annotations

import json
import logging
import sys

from app.logging import JsonLogFormatter, configure_logging, log_kv


def test_log_kv_keeps_text_rendering_for_local_logs() -> None:
    message = log_kv(
        "message_processed",
        chat_id=123,
        delivered=True,
        latency_ms=42,
        skipped=None,
    )

    assert str(message) == "message_processed chat_id=123 delivered=True latency_ms=42"


def test_json_formatter_emits_event_and_typed_fields() -> None:
    formatter = JsonLogFormatter()
    record = logging.LogRecord(
        name="app.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=log_kv(
            "message_processed",
            chat_id=123,
            delivered=True,
            latency_ms=42,
            skipped=None,
        ),
        args=(),
        exc_info=None,
    )

    payload = json.loads(formatter.format(record))

    assert payload["level"] == "INFO"
    assert payload["logger"] == "app.test"
    assert payload["event"] == "message_processed"
    assert payload["chat_id"] == 123
    assert payload["delivered"] is True
    assert payload["latency_ms"] == 42
    assert "skipped" not in payload
    assert "timestamp" in payload


def test_json_formatter_serializes_exception_details() -> None:
    formatter = JsonLogFormatter()
    try:
        raise RuntimeError("delivery timed out")
    except RuntimeError:
        exc_info = sys.exc_info()

    record = logging.LogRecord(
        name="app.test",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg=log_kv("video_job_delivery_exception", chat_id=123),
        args=(),
        exc_info=exc_info,
    )

    payload = json.loads(formatter.format(record))

    assert payload["event"] == "video_job_delivery_exception"
    assert payload["exception_type"] == "RuntimeError"
    assert payload["exception_message"] == "delivery timed out"
    assert "RuntimeError: delivery timed out" in payload["exception_traceback"]


def test_configure_logging_installs_json_formatter_and_suppresses_http_clients() -> None:
    root_logger = logging.getLogger()
    original_handlers = list(root_logger.handlers)
    original_level = root_logger.level
    original_httpx_level = logging.getLogger("httpx").level
    original_httpcore_level = logging.getLogger("httpcore").level

    try:
        configure_logging("DEBUG", log_format="json")

        assert root_logger.level == logging.DEBUG
        assert root_logger.handlers
        assert isinstance(root_logger.handlers[0].formatter, JsonLogFormatter)
        assert logging.getLogger("httpx").level == logging.WARNING
        assert logging.getLogger("httpcore").level == logging.WARNING
    finally:
        root_logger.handlers[:] = original_handlers
        root_logger.setLevel(original_level)
        logging.getLogger("httpx").setLevel(original_httpx_level)
        logging.getLogger("httpcore").setLevel(original_httpcore_level)
