from datetime import datetime
from typing import Literal

CheckStatus = Literal["baseline", "unchanged", "changed", "blocked", "error"]
MonitorKind = Literal["website", "gmail"]

from pydantic import BaseModel, Field, model_validator


class HealthResponse(BaseModel):
    status: str
    service: str


class SystemStatusResponse(BaseModel):
    backend: Literal["ok"] = "ok"
    enabled_monitors: int
    total_monitors: int
    last_checked_at: datetime | None = None
    scheduler_interval_seconds: int = 10
    scheduler_interval_minutes: int = 0
    scheduler: Literal["ok", "stale", "never", "idle"]
    message: str


class MonitorCreate(BaseModel):
    goal: str = Field(..., min_length=1)
    url: str | None = None
    kind: MonitorKind = "website"

    @model_validator(mode="after")
    def require_url_for_website(self) -> "MonitorCreate":
        if self.kind == "website" and not (self.url or "").strip():
            raise ValueError("url is required for website monitors.")
        return self


class MonitorUpdate(BaseModel):
    enabled: bool


class AgentTraceEntry(BaseModel):
    agent: Literal["supervisor", "monitoring", "analysis", "action"]
    role: str
    summary: str


class ObservedFact(BaseModel):
    field: str | None = None
    value: str
    evidence: str | None = None
    source_excerpt: str | None = None
    heading: str | None = None


class ObservationRecord(BaseModel):
    id: str
    monitor_id: str
    content_hash: str
    summary: str
    checked_at: datetime
    meaningful_change: bool | None = None
    reason: str | None = None
    action_required: bool | None = None
    change_status: CheckStatus | None = None
    agents: list[str] = Field(default_factory=list)
    agent_trace: list[AgentTraceEntry] = Field(default_factory=list)
    observed_facts: list[str] = Field(default_factory=list)
    observed_fact_records: list[ObservedFact] = Field(default_factory=list)
    relevant_excerpt: str | None = None
    title: str | None = None
    fetch_method: Literal["http", "browser"] | None = None
    source_url: str | None = None


class MonitorRecord(BaseModel):
    id: str
    task_id: str
    goal: str
    url: str
    kind: MonitorKind = "website"
    name: str | None = None
    enabled: bool = True
    created_at: datetime
    updated_at: datetime | None = None
    last_checked_at: datetime | None = None
    last_changed_at: datetime | None = None
    previous_content: str | None = Field(default=None, exclude=True)
    previous_content_hash: str | None = None
    last_change: str | None = None
    initialized: bool = False
    status: str


class MonitorListResponse(BaseModel):
    monitors: list[MonitorRecord]


class GmailMatchedEmail(BaseModel):
    id: str
    monitor_id: str
    message_id: str
    alert_id: str | None = None
    subject: str
    sender: str
    received_at: datetime | None = None
    preview: str
    relevant: bool = True
    reason: str
    summary: str
    action: str = "Alert user"
    created_at: datetime


class MonitorDetailResponse(MonitorRecord):
    latest_observation: ObservationRecord | None = None
    observations: list[ObservationRecord] = Field(default_factory=list)
    matched_emails: list[GmailMatchedEmail] = Field(default_factory=list)
    last_email_received_at: datetime | None = None


class MonitorCheckResponse(BaseModel):
    monitor_id: str
    goal: str
    url: str
    status: Literal["initialized", "unchanged", "changed", "blocked", "error"]
    changed: bool
    change_status: CheckStatus
    hash_changed: bool = False
    summary: str
    message: str | None = None
    old_content: str | None = None
    new_content: str | None = None
    previous_checked_at: datetime | None = None
    checked_at: datetime
    tool_used: bool
    content_hash: str
    meaningful_change: bool | None = None
    reason: str | None = None
    action_required: bool | None = None
    alert_id: str | None = None
    action_type: str | None = None
    human_loop_state: str | None = None
    user_notification: str | None = None
    notification_status: str | None = None
    agents: list[str] = Field(default_factory=list)
    agent_trace: list[AgentTraceEntry] = Field(default_factory=list)
    observed_facts: list[str] = Field(default_factory=list)
    observed_fact_records: list[ObservedFact] = Field(default_factory=list)
    relevant_excerpt: str | None = None
    fetch_method: Literal["http", "browser"] | None = None
    title: str | None = None
    result_status: str | None = None
    previous_observation: str | None = None
    current_observation: str | None = None


class WebpageObservation(BaseModel):
    url: str
    status_code: int
    title: str | None = None
    text: str
    content_hash: str
    fetched_at: datetime
    final_url: str | None = None
    fetch_method: Literal["http", "browser"] = "http"
    raw_bytes: int | None = None
    readable_chars: int | None = None
    normalized_chars: int | None = None


class SentinelResult(BaseModel):
    goal: str
    url: str
    summary: str
    tool_used: bool
    model: str
    content_hash: str | None = None
    tool_error: str | None = None
    page_text: str | None = None
    title: str | None = None
    fetch_method: Literal["http", "browser"] | None = None
    observation_status: Literal["ok", "blocked_requires_user", "error"] | None = None
    relevant_excerpt: str | None = None
    observed_facts: list[str] = Field(default_factory=list)
    observed_fact_records: list[ObservedFact] = Field(default_factory=list)
    reasoning: str | None = None


class MeaningfulChangeAssessment(BaseModel):
    meaningful_change: bool
    summary: str
    reason: str
    action_required: bool
    confidence: float | None = None
    changed_items: list[str] = Field(default_factory=list)
    previous_relevant_content: str | None = None
    current_relevant_content: str | None = None


class AgentTask(BaseModel):
    goal: str
    url: str | None = None
    source_type: str = "webpage"
    previous_excerpt: str | None = None
    current_excerpt: str | None = None
    change_status: Literal["baseline", "unchanged", "changed"] | None = None


class MonitoringObservation(BaseModel):
    source_type: str = "webpage"
    url: str | None = None
    summary: str
    content_hash: str | None = None
    tool_used: bool = False
    tool_error: str | None = None
    page_text: str | None = Field(default=None, exclude=True)
    relevant_excerpt: str | None = None
    observed_facts: list[str] = Field(default_factory=list)
    observed_fact_records: list[ObservedFact] = Field(default_factory=list)
    fetch_method: Literal["http", "browser"] | None = None
    status: Literal["ok", "blocked_requires_user", "error"] | None = None
    title: str | None = None


class ChangeAnalysis(MeaningfulChangeAssessment):
    pass


ActionType = Literal["ignore", "create_alert", "notify_user", "request_approval"]
HumanLoopState = Literal[
    "no_action",
    "notification",
    "approval_required",
    "blocked_requires_user",
]


class ActionDecision(BaseModel):
    action_type: ActionType
    human_loop_state: HumanLoopState
    summary: str
    reason: str
    user_notification: str | None = None
    requires_approval: bool = False
    blocked_reason: str | None = None


class SupervisorResult(BaseModel):
    goal: str
    change_status: Literal["baseline", "unchanged", "changed"] | None = None
    observation: MonitoringObservation | None = None
    analysis: ChangeAnalysis | None = None
    action: ActionDecision | None = None
    summary: str
    agents_invoked: list[str]


AlertStatus = Literal["pending", "acknowledged", "dismissed"]


class AlertRecord(BaseModel):
    id: str
    alert_id: str
    monitor_id: str
    content_hash: str
    summary: str
    reason: str
    action_required: bool
    status: AlertStatus
    created_at: datetime
    updated_at: datetime | None = None
    action_type: str | None = None
    human_loop_state: str | None = None
    user_notification: str | None = None
    notification_status: str | None = None
    source: str = "website"


class AlertListResponse(BaseModel):
    alerts: list[AlertRecord]


class AlertUpdate(BaseModel):
    status: AlertStatus


class ActionHistoryRecord(BaseModel):
    id: str
    action_id: str
    monitor_id: str
    alert_id: str | None = None
    action_type: str
    human_loop_state: str
    summary: str
    created_at: datetime


class NotificationResult(BaseModel):
    sent: bool
    channel: str
    status: Literal["sent", "skipped", "failed", "disabled"]
    message: str | None = None
    mocked: bool = False


class GmailStatusResponse(BaseModel):
    status: Literal[
        "NOT_CONNECTED",
        "CONNECTING",
        "CONNECTED",
        "WATCH_ACTIVE",
        "WATCH_EXPIRED",
        "ERROR",
        "DISCONNECTED",
    ]
    google_email: str | None = None
    connected_at: datetime | None = None
    watch_expiration: datetime | None = None
    last_email_received_at: datetime | None = None
    configured: bool = False
    message: str | None = None


class GmailConnectResponse(BaseModel):
    authorization_url: str


class GmailRelevanceAssessment(BaseModel):
    relevant: bool
    monitor_id: str | None = None
    summary: str
    reason: str
    action_required: bool = False


class GmailEmail(BaseModel):
    message_id: str
    thread_id: str | None = None
    sender: str
    subject: str
    received_at: datetime | None = None
    body_text: str
    labels: list[str] = Field(default_factory=list)
    attachments: list[str] = Field(default_factory=list)


class GmailIngestResult(BaseModel):
    processed: int = 0
    skipped: int = 0
    alerts_created: int = 0
    status: str = "ok"
    message: str | None = None
