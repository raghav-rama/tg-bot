from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError as PydanticValidationError

from aiogram.types import Update

router = APIRouter()


@router.post("/telegram/webhook")
async def telegram_webhook(request: Request) -> JSONResponse:
    container = request.app.state.container
    if container.settings is None or container.telegram_runtime is None:
        return JSONResponse(status_code=503, content={"ok": False})

    if container.settings.app_update_mode != "webhook":
        return JSONResponse(
            status_code=503,
            content={"ok": False, "detail": "webhook mode is not enabled"},
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

