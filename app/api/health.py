from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter()


@router.get("/healthz")
async def healthz() -> dict[str, bool]:
    return {"ok": True}


@router.get("/readyz")
async def readyz(request: Request) -> JSONResponse:
    container = request.app.state.container
    ready = True
    detail = None

    if container.startup_error is not None:
        ready = False
        detail = container.startup_error
    elif container.settings is None or container.database is None or container.chat_service is None:
        ready = False
        detail = "application dependencies are not initialized"
    elif (
        container.settings.app_update_mode == "polling"
        and container.telegram_runtime is not None
        and container.telegram_runtime.last_error is not None
    ):
        ready = False
        detail = f"telegram polling failed: {type(container.telegram_runtime.last_error).__name__}"
    elif (
        container.settings.app_update_mode == "webhook"
        and (
            container.telegram_runtime is None
            or not container.telegram_runtime.webhook_configured
        )
    ):
        ready = False
        detail = "telegram webhook is not configured"

    status_code = 200 if ready else 503
    payload: dict[str, object] = {"ok": ready}
    if detail is not None:
        payload["detail"] = detail
    return JSONResponse(status_code=status_code, content=payload)
