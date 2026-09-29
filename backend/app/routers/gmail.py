from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import RedirectResponse

from app.config import get_settings, resolved_frontend_url
from app.identity import attach_user_cookie, resolve_user_id
from app.integrations.gmail_client import GmailClientError
from app.models.schemas import (
    GmailConnectResponse,
    GmailEmail,
    GmailIngestResult,
    GmailStatusResponse,
)
from app.services import gmail as gmail_service
from app.storage.database import MonitorStore

router = APIRouter()


def _store(request: Request) -> MonitorStore:
    return request.app.state.store


def _gmail_http_error(exc: GmailClientError) -> HTTPException:
    status = 400
    if exc.code == "not_configured":
        status = 503
    elif exc.code == "not_connected":
        status = 409
    elif exc.code == "invalid_webhook":
        status = 401
    elif exc.code in {"token_refresh_failed", "gmail_api_failure", "watch_failed"}:
        status = 502
    return HTTPException(
        status_code=status,
        detail={"error": exc.code, "message": exc.message, "status_code": None},
    )


@router.get("/api/integrations/gmail/connect", response_model=GmailConnectResponse)
def gmail_connect(request: Request, response: Response) -> GmailConnectResponse:
    user_id = resolve_user_id(request)
    try:
        result = gmail_service.start_oauth(_store(request), user_id)
    except GmailClientError as exc:
        raise _gmail_http_error(exc) from exc
    attach_user_cookie(response, user_id, request=request)
    return result


@router.get("/api/integrations/gmail/callback")
def gmail_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    frontend = resolved_frontend_url()
    target = frontend or ""
    if error or not code or not state:
        redirect = RedirectResponse(f"{target}/?gmail=error", status_code=302)
        user_id = resolve_user_id(request)
        attach_user_cookie(redirect, user_id, request=request)
        return redirect
    try:
        connection = gmail_service.complete_oauth(_store(request), code=code, state=state)
        user_id = str(connection.get("user_id") or resolve_user_id(request))
    except GmailClientError:
        redirect = RedirectResponse(f"{target}/?gmail=error", status_code=302)
        attach_user_cookie(redirect, resolve_user_id(request), request=request)
        return redirect
    redirect = RedirectResponse(f"{target}/?gmail=connected", status_code=302)
    attach_user_cookie(redirect, user_id, request=request)
    return redirect


@router.get("/api/integrations/gmail/status", response_model=GmailStatusResponse)
def gmail_status(request: Request, response: Response) -> GmailStatusResponse:
    user_id = resolve_user_id(request)
    attach_user_cookie(response, user_id, request=request)
    return gmail_service.connection_status(_store(request), user_id)


@router.post("/api/integrations/gmail/disconnect", response_model=GmailStatusResponse)
def gmail_disconnect(request: Request, response: Response) -> GmailStatusResponse:
    user_id = resolve_user_id(request)
    result = gmail_service.disconnect_gmail(_store(request), user_id)
    attach_user_cookie(response, user_id, request=request)
    return result


@router.post("/api/webhooks/gmail", response_model=GmailIngestResult)
def gmail_webhook(
    request: Request,
    payload: dict,
    token: str | None = Query(default=None),
) -> GmailIngestResult:
    try:
        return gmail_service.handle_pubsub_push(_store(request), payload, token=token)
    except GmailClientError as exc:
        raise _gmail_http_error(exc) from exc


@router.post("/api/integrations/gmail/dev/ingest", response_model=GmailIngestResult)
def gmail_dev_ingest(body: GmailEmail, request: Request, response: Response) -> GmailIngestResult:
    settings = get_settings()
    if not settings.gmail_dev_ingest:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "not_found",
                "message": "Gmail local ingest is disabled.",
                "status_code": None,
            },
        )
    user_id = resolve_user_id(request)
    attach_user_cookie(response, user_id, request=request)
    result = gmail_service.process_email(_store(request), body, user_id=user_id)
    alerts = 1 if result == "alerted" else 0
    skipped = 1 if result in {"skipped", "duplicate", "ignored"} else 0
    return GmailIngestResult(
        processed=1,
        skipped=skipped,
        alerts_created=alerts,
        status=result,
    )
