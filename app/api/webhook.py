from __future__ import annotations

import secrets

from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError as PydanticValidationError

from aiogram.types import Update

router = APIRouter()


@router.post("/telegram/webhook")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(
        default=None,
        alias="X-Telegram-Bot-Api-Secret-Token",
    ),
) -> JSONResponse:
    container = request.app.state.container
    if container.settings is None or container.telegram_runtime is None:
        return JSONResponse(status_code=503, content={"ok": False})

    if container.settings.app_update_mode != "webhook":
        return JSONResponse(
            status_code=503,
            content={"ok": False, "detail": "webhook mode is not enabled"},
        )

    expected_secret = (
        container.settings.telegram_webhook_secret_token.get_secret_value()
        if container.settings.telegram_webhook_secret_token is not None
        else None
    )
    if expected_secret is None:
        return JSONResponse(
            status_code=503,
            content={"ok": False, "detail": "webhook secret is not configured"},
        )
    if x_telegram_bot_api_secret_token is None or not secrets.compare_digest(
        x_telegram_bot_api_secret_token,
        expected_secret,
    ):
        return JSONResponse(
            status_code=401,
            content={"ok": False, "detail": "invalid webhook secret"},
        )

    payload = await request.json()
    try:
        update = Update.model_validate(payload, context={"bot": container.telegram_runtime.bot})
    except PydanticValidationError as exc:
        return JSONResponse(
            status_code=400,
            content={"ok": False, "detail": exc.errors()},
        )

    await container.telegram_runtime.feed_update(update)
    return JSONResponse(status_code=200, content={"ok": True})
