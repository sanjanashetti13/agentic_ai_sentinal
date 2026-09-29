from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from app.config import cors_origin_list, get_settings
from app.identity import attach_user_cookie, resolve_user_id
from app.models.schemas import (
    AlertListResponse,
    AlertRecord,
    AlertStatus,
    AlertUpdate,
    GmailMatchedEmail,
    HealthResponse,
    MonitorCheckResponse,
    MonitorCreate,
    MonitorDetailResponse,
    MonitorListResponse,
    MonitorRecord,
    MonitorUpdate,
    NotificationResult,
    ObservationRecord,
    SystemStatusResponse,
)
from app.routers.gmail import router as gmail_router
from app.services.gmail import start_mailbox_sync, stop_mailbox_sync
from app.services.monitoring import (
    MonitoringCheckError,
    create_monitor_record,
    run_monitor_check,
    system_status,
)
from app.services.notifications import notify_alert
from app.storage.database import MonitorStore
from app.tools.web_monitor import WebpageToolError

logger = logging.getLogger("sentinel.website_monitor")


@asynccontextmanager
async def lifespan(app: FastAPI):
    sentinel = logging.getLogger("sentinel")
    sentinel.setLevel(logging.INFO)
    if not sentinel.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))
        sentinel.addHandler(handler)
    settings = get_settings()
    store = MonitorStore(settings.database_path)
    store.initialize()
    app.state.store = store
    start_mailbox_sync(store)
    try:
        yield
    finally:
        stop_mailbox_sync()


app = FastAPI(
    title="Sentinel",
    description="Autonomous personal digital monitoring agent",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origin_list(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(gmail_router)


def _store(request: Request) -> MonitorStore:
    return request.app.state.store


def _monitor_record(item: dict) -> MonitorRecord:
    return MonitorRecord.model_validate(item)


def _not_found(monitor_id: str) -> HTTPException:
    return HTTPException(
        status_code=404,
        detail={
            "error": "not_found",
            "message": f"Monitor {monitor_id} was not found.",
            "status_code": None,
        },
    )


def _alert_not_found(alert_id: str) -> HTTPException:
    return HTTPException(
        status_code=404,
        detail={
            "error": "not_found",
            "message": f"Alert {alert_id} was not found.",
            "status_code": None,
        },
    )


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok", service="sentinel")


@app.get("/api/status", response_model=SystemStatusResponse)
def get_status(request: Request) -> SystemStatusResponse:
    return system_status(_store(request))


@app.post("/api/monitors", response_model=MonitorRecord)
def create_monitor(body: MonitorCreate, request: Request, response: Response) -> MonitorRecord:
    user_id = resolve_user_id(request)
    try:
        created = create_monitor_record(
            _store(request),
            body.goal,
            body.url,
            user_id=user_id,
            kind=body.kind,
        )
    except WebpageToolError as exc:
        raise HTTPException(status_code=422, detail=exc.to_dict()) from exc
    attach_user_cookie(response, user_id, request=request)
    return _monitor_record(created)


@app.get("/api/monitors", response_model=MonitorListResponse)
def list_monitors(request: Request) -> MonitorListResponse:
    records = [_monitor_record(item) for item in _store(request).list_monitors()]
    return MonitorListResponse(monitors=records)


@app.get("/api/monitors/{monitor_id}", response_model=MonitorDetailResponse)
def get_monitor(monitor_id: str, request: Request) -> MonitorDetailResponse:
    store = _store(request)
    monitor = store.get_monitor(monitor_id)
    if monitor is None:
        raise _not_found(monitor_id)
    latest = store.get_latest_observation(monitor_id)
    observations = store.list_observations(monitor_id)
    payload = dict(monitor)
    payload["latest_observation"] = (
        ObservationRecord.model_validate(latest) if latest else None
    )
    payload["observations"] = [
        ObservationRecord.model_validate(item) for item in observations
    ]
    if monitor.get("kind") == "gmail":
        payload["matched_emails"] = [
            GmailMatchedEmail.model_validate(item)
            for item in store.list_gmail_matches(monitor_id)
        ]
        user_id = resolve_user_id(request)
        connection = store.get_gmail_connection(user_id)
        payload["last_email_received_at"] = (
            connection.get("last_email_received_at") if connection else None
        )
    return MonitorDetailResponse.model_validate(payload)


@app.patch("/api/monitors/{monitor_id}", response_model=MonitorRecord)
def update_monitor(
    monitor_id: str,
    body: MonitorUpdate,
    request: Request,
) -> MonitorRecord:
    updated = _store(request).set_enabled(monitor_id, body.enabled)
    if updated is None:
        raise _not_found(monitor_id)
    return _monitor_record(updated)


@app.delete("/api/monitors/{monitor_id}", status_code=204)
def delete_monitor(monitor_id: str, request: Request) -> None:
    deleted = _store(request).delete_monitor(monitor_id)
    if not deleted:
        raise _not_found(monitor_id)


@app.post("/api/monitors/{monitor_id}/check", response_model=MonitorCheckResponse)
def check_monitor(monitor_id: str, request: Request) -> MonitorCheckResponse:
    store = _store(request)
    if store.get_monitor(monitor_id) is None:
        raise _not_found(monitor_id)
    try:
        return run_monitor_check(store, monitor_id)
    except KeyError:
        raise _not_found(monitor_id) from None
    except MonitoringCheckError as exc:
        raise HTTPException(
            status_code=exc.http_status,
            detail=exc.to_dict(),
        ) from exc


def _alert_record(item: dict) -> AlertRecord:
    return AlertRecord.model_validate(item)


@app.get("/api/alerts", response_model=AlertListResponse)
def list_alerts(
    request: Request,
    status: AlertStatus | None = None,
) -> AlertListResponse:
    records = [
        _alert_record(item) for item in _store(request).list_alerts(status=status)
    ]
    return AlertListResponse(alerts=records)


@app.get("/api/alerts/{alert_id}", response_model=AlertRecord)
def get_alert(alert_id: str, request: Request) -> AlertRecord:
    alert = _store(request).get_alert(alert_id)
    if alert is None:
        raise _alert_not_found(alert_id)
    return _alert_record(alert)


@app.patch("/api/alerts/{alert_id}", response_model=AlertRecord)
def update_alert(
    alert_id: str,
    body: AlertUpdate,
    request: Request,
) -> AlertRecord:
    updated = _store(request).set_alert_status(alert_id, body.status)
    if updated is None:
        raise _alert_not_found(alert_id)
    return _alert_record(updated)


@app.post("/api/alerts/{alert_id}/notify", response_model=NotificationResult)
def send_alert_notification(alert_id: str, request: Request) -> NotificationResult:
    store = _store(request)
    if store.get_alert(alert_id) is None:
        raise _alert_not_found(alert_id)
    return notify_alert(store, alert_id)
