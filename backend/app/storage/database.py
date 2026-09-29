from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _row_keys(row: sqlite3.Row) -> set[str]:
    return set(row.keys())


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


def _row_to_monitor(row: sqlite3.Row) -> dict[str, Any]:
    keys = _row_keys(row)
    task_id = row["task_id"]
    enabled = True
    if "enabled" in keys:
        enabled = bool(row["enabled"])
    return {
        "id": task_id,
        "task_id": task_id,
        "goal": row["goal"],
        "url": row["url"],
        "enabled": enabled,
        "created_at": datetime.fromisoformat(row["created_at"]),
        "updated_at": _parse_datetime(row["updated_at"] if "updated_at" in keys else None),
        "last_checked_at": _parse_datetime(row["last_checked_at"]),
        "last_changed_at": _parse_datetime(
            row["last_changed_at"] if "last_changed_at" in keys else None
        ),
        "previous_content": row["previous_content"],
        "previous_content_hash": row["previous_content_hash"],
        "last_change": row["last_change"],
        "initialized": row["previous_content_hash"] is not None,
        "status": row["status"],
        "user_id": row["user_id"] if "user_id" in keys else None,
        "kind": row["kind"] if "kind" in keys and row["kind"] else "website",
        "name": row["name"] if "name" in keys else None,
    }


def _optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    return bool(value)


def _parse_json_list(value: Any) -> list:
    if not value:
        return []
    if isinstance(value, list):
        return value
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def _row_to_observation(row: sqlite3.Row) -> dict[str, Any]:
    keys = _row_keys(row)
    return {
        "id": row["observation_id"],
        "monitor_id": row["monitor_id"],
        "content_hash": row["content_hash"],
        "summary": row["summary"],
        "checked_at": datetime.fromisoformat(row["checked_at"]),
        "meaningful_change": _optional_bool(
            row["meaningful_change"] if "meaningful_change" in keys else None
        ),
        "reason": row["reason"] if "reason" in keys else None,
        "action_required": _optional_bool(
            row["action_required"] if "action_required" in keys else None
        ),
        "change_status": row["change_status"] if "change_status" in keys else None,
        "agents": _parse_json_list(row["agents"] if "agents" in keys else None),
        "agent_trace": _parse_json_list(
            row["agent_trace"] if "agent_trace" in keys else None
        ),
        "observed_facts": _parse_json_list(
            row["observed_facts"] if "observed_facts" in keys else None
        ),
        "observed_fact_records": _parse_json_list(
            row["observed_fact_records"] if "observed_fact_records" in keys else None
        ),
        "relevant_excerpt": row["relevant_excerpt"]
        if "relevant_excerpt" in keys
        else None,
        "title": row["title"] if "title" in keys else None,
        "fetch_method": row["fetch_method"] if "fetch_method" in keys else None,
        "source_url": row["source_url"] if "source_url" in keys else None,
    }


def _row_to_alert(row: sqlite3.Row) -> dict[str, Any]:
    keys = _row_keys(row)
    alert_id = row["alert_id"]
    return {
        "id": alert_id,
        "alert_id": alert_id,
        "monitor_id": row["monitor_id"],
        "content_hash": row["content_hash"],
        "summary": row["summary"],
        "reason": row["reason"],
        "action_required": bool(row["action_required"]),
        "status": row["status"],
        "created_at": datetime.fromisoformat(row["created_at"]),
        "updated_at": _parse_datetime(row["updated_at"] if "updated_at" in keys else None),
        "action_type": row["action_type"] if "action_type" in keys else None,
        "human_loop_state": row["human_loop_state"] if "human_loop_state" in keys else None,
        "user_notification": row["user_notification"] if "user_notification" in keys else None,
        "notification_status": (
            row["notification_status"] if "notification_status" in keys else None
        ),
        "source": row["source"] if "source" in keys else "website",
    }


def _row_to_action_history(row: sqlite3.Row) -> dict[str, Any]:
    action_id = row["action_id"]
    return {
        "id": action_id,
        "action_id": action_id,
        "monitor_id": row["monitor_id"],
        "alert_id": row["alert_id"],
        "action_type": row["action_type"],
        "human_loop_state": row["human_loop_state"],
        "summary": row["summary"],
        "created_at": datetime.fromisoformat(row["created_at"]),
    }


OAUTH_STATE_TTL = timedelta(minutes=15)


def _require_gmail_user_id(user_id: str) -> str:
    value = str(user_id or "").strip()
    if not value:
        raise ValueError("A SENTINEL user_id is required for Gmail storage.")
    return value


def _normalize_google_email(email: str) -> str:
    return str(email or "").strip().lower()


def _row_to_gmail_connection(row: sqlite3.Row) -> dict[str, Any]:
    keys = _row_keys(row)
    return {
        "id": row["user_id"],
        "user_id": row["user_id"],
        "google_email": row["google_email"],
        "token_blob": row["token_blob"],
        "last_history_id": row["last_history_id"],
        "watch_expiration": _parse_datetime(row["watch_expiration"]),
        "status": row["status"],
        "error_message": row["error_message"],
        "connected_at": datetime.fromisoformat(row["connected_at"]),
        "created_at": datetime.fromisoformat(row["created_at"]),
        "updated_at": datetime.fromisoformat(row["updated_at"]),
        "last_email_received_at": _parse_datetime(
            row["last_email_received_at"] if "last_email_received_at" in keys else None
        ),
    }


def derive_monitor_name(goal: str) -> str:
    text = " ".join((goal or "").split())
    lowered = text.lower()
    for marker in (" about ", " for "):
        index = lowered.find(marker)
        if index >= 0:
            remainder = text[index + len(marker) :].strip(" .")
            if remainder:
                text = remainder[0].upper() + remainder[1:]
                break
    if not text:
        return "Monitor"
    if len(text) <= 72:
        return text
    return text[:69].rstrip() + "…"


def _row_to_gmail_match(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["match_id"],
        "monitor_id": row["monitor_id"],
        "message_id": row["message_id"],
        "alert_id": row["alert_id"],
        "subject": row["subject"] or "",
        "sender": row["sender"] or "",
        "received_at": _parse_datetime(row["received_at"]),
        "preview": row["preview"] or "",
        "relevant": bool(row["relevant"]),
        "reason": row["reason"] or "",
        "summary": row["summary"] or "",
        "action": row["action"] or "Alert user",
        "created_at": datetime.fromisoformat(row["created_at"]),
    }


GMAIL_MONITOR_URL = "gmail://inbox"


class MonitorStore:
    """SQLite persistence for monitoring tasks.

    The interface is intentionally small so a later PostgreSQL store
    can implement the same methods without changing API or services.
    """

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        parent = Path(db_path).parent
        if str(parent) not in (".", ""):
            parent.mkdir(parents=True, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS monitors (
                    task_id TEXT PRIMARY KEY,
                    goal TEXT NOT NULL,
                    url TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    last_checked_at TEXT,
                    previous_content TEXT,
                    previous_content_hash TEXT,
                    last_change TEXT,
                    last_changed_at TEXT,
                    status TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    updated_at TEXT
                )
                """
            )
            self._ensure_monitor_columns(connection)
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS observations (
                    observation_id TEXT PRIMARY KEY,
                    monitor_id TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    checked_at TEXT NOT NULL,
                    meaningful_change INTEGER,
                    reason TEXT,
                    action_required INTEGER,
                    FOREIGN KEY (monitor_id) REFERENCES monitors(task_id)
                )
                """
            )
            self._ensure_observation_columns(connection)
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_observations_monitor_checked
                ON observations (monitor_id, checked_at DESC)
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS alerts (
                    alert_id TEXT PRIMARY KEY,
                    monitor_id TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    action_required INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT,
                    FOREIGN KEY (monitor_id) REFERENCES monitors(task_id)
                )
                """
            )
            connection.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_alerts_monitor_hash
                ON alerts (monitor_id, content_hash)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_alerts_created
                ON alerts (created_at DESC)
                """
            )
            self._ensure_alert_columns(connection)
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS action_history (
                    action_id TEXT PRIMARY KEY,
                    monitor_id TEXT NOT NULL,
                    alert_id TEXT,
                    action_type TEXT NOT NULL,
                    human_loop_state TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (monitor_id) REFERENCES monitors(task_id)
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_action_history_monitor
                ON action_history (monitor_id, created_at DESC)
                """
            )
            self._ensure_gmail_tables(connection)
            connection.commit()

    def _ensure_monitor_columns(self, connection: sqlite3.Connection) -> None:
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(monitors)").fetchall()
        }
        if "enabled" not in columns:
            connection.execute(
                "ALTER TABLE monitors ADD COLUMN enabled INTEGER NOT NULL DEFAULT 1"
            )
        if "updated_at" not in columns:
            connection.execute("ALTER TABLE monitors ADD COLUMN updated_at TEXT")
        if "last_changed_at" not in columns:
            connection.execute("ALTER TABLE monitors ADD COLUMN last_changed_at TEXT")
        if "user_id" not in columns:
            connection.execute("ALTER TABLE monitors ADD COLUMN user_id TEXT")
        if "kind" not in columns:
            connection.execute(
                "ALTER TABLE monitors ADD COLUMN kind TEXT NOT NULL DEFAULT 'website'"
            )
        if "name" not in columns:
            connection.execute("ALTER TABLE monitors ADD COLUMN name TEXT")

    def _ensure_observation_columns(self, connection: sqlite3.Connection) -> None:
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(observations)").fetchall()
        }
        if "meaningful_change" not in columns:
            connection.execute("ALTER TABLE observations ADD COLUMN meaningful_change INTEGER")
        if "reason" not in columns:
            connection.execute("ALTER TABLE observations ADD COLUMN reason TEXT")
        if "action_required" not in columns:
            connection.execute("ALTER TABLE observations ADD COLUMN action_required INTEGER")
        if "change_status" not in columns:
            connection.execute("ALTER TABLE observations ADD COLUMN change_status TEXT")
        if "agents" not in columns:
            connection.execute("ALTER TABLE observations ADD COLUMN agents TEXT")
        if "agent_trace" not in columns:
            connection.execute("ALTER TABLE observations ADD COLUMN agent_trace TEXT")
        if "observed_facts" not in columns:
            connection.execute("ALTER TABLE observations ADD COLUMN observed_facts TEXT")
        if "observed_fact_records" not in columns:
            connection.execute(
                "ALTER TABLE observations ADD COLUMN observed_fact_records TEXT"
            )
        if "relevant_excerpt" not in columns:
            connection.execute("ALTER TABLE observations ADD COLUMN relevant_excerpt TEXT")
        if "title" not in columns:
            connection.execute("ALTER TABLE observations ADD COLUMN title TEXT")
        if "fetch_method" not in columns:
            connection.execute("ALTER TABLE observations ADD COLUMN fetch_method TEXT")
        if "source_url" not in columns:
            connection.execute("ALTER TABLE observations ADD COLUMN source_url TEXT")

    def _ensure_alert_columns(self, connection: sqlite3.Connection) -> None:
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(alerts)").fetchall()
        }
        if "action_type" not in columns:
            connection.execute("ALTER TABLE alerts ADD COLUMN action_type TEXT")
        if "human_loop_state" not in columns:
            connection.execute("ALTER TABLE alerts ADD COLUMN human_loop_state TEXT")
        if "user_notification" not in columns:
            connection.execute("ALTER TABLE alerts ADD COLUMN user_notification TEXT")
        if "notification_status" not in columns:
            connection.execute("ALTER TABLE alerts ADD COLUMN notification_status TEXT")
        if "source" not in columns:
            connection.execute(
                "ALTER TABLE alerts ADD COLUMN source TEXT NOT NULL DEFAULT 'website'"
            )

    def _ensure_gmail_tables(self, connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS gmail_connections (
                user_id TEXT PRIMARY KEY,
                google_email TEXT NOT NULL,
                token_blob TEXT NOT NULL,
                last_history_id TEXT,
                watch_expiration TEXT,
                status TEXT NOT NULL,
                error_message TEXT,
                connected_at TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS gmail_oauth_states (
                state TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS gmail_processed_messages (
                user_id TEXT NOT NULL,
                message_id TEXT NOT NULL,
                processed_at TEXT NOT NULL,
                PRIMARY KEY (user_id, message_id)
            )
            """
        )

        connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_gmail_connections_email
            ON gmail_connections (google_email)
            """
        )
        self._ensure_gmail_schema(connection)
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS gmail_matches (
                match_id TEXT PRIMARY KEY,
                monitor_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                message_id TEXT NOT NULL,
                alert_id TEXT,
                subject TEXT,
                sender TEXT,
                received_at TEXT,
                preview TEXT,
                relevant INTEGER NOT NULL DEFAULT 1,
                reason TEXT,
                summary TEXT,
                action TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (monitor_id) REFERENCES monitors(task_id)
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_gmail_matches_monitor
            ON gmail_matches (monitor_id, created_at DESC)
            """
        )

    def _ensure_gmail_schema(self, connection: sqlite3.Connection) -> None:
        oauth_columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(gmail_oauth_states)").fetchall()
        }
        if "user_id" not in oauth_columns:
            connection.execute(
                "ALTER TABLE gmail_oauth_states ADD COLUMN user_id TEXT NOT NULL DEFAULT ''"
            )
        processed_columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(gmail_processed_messages)"
            ).fetchall()
        }
        if "user_id" not in processed_columns:
            connection.execute("DROP TABLE IF EXISTS gmail_processed_messages")
            connection.execute(
                """
                CREATE TABLE gmail_processed_messages (
                    user_id TEXT NOT NULL,
                    message_id TEXT NOT NULL,
                    processed_at TEXT NOT NULL,
                    PRIMARY KEY (user_id, message_id)
                )
                """
            )
        connection_columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(gmail_connections)").fetchall()
        }
        if "last_email_received_at" not in connection_columns:
            connection.execute(
                "ALTER TABLE gmail_connections ADD COLUMN last_email_received_at TEXT"
            )

    def create_monitor(
        self,
        goal: str,
        url: str,
        user_id: str | None = None,
        *,
        kind: str = "website",
        name: str | None = None,
    ) -> dict[str, Any]:
        task_id = str(uuid.uuid4())
        created_at = utc_now().isoformat()
        kind = kind if kind in {"website", "gmail"} else "website"
        display_name = (name or derive_monitor_name(goal)).strip() or derive_monitor_name(goal)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO monitors (
                    task_id, goal, url, created_at, status, enabled, updated_at,
                    user_id, kind, name
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    goal.strip(),
                    url.strip(),
                    created_at,
                    "created",
                    1,
                    created_at,
                    user_id,
                    kind,
                    display_name,
                ),
            )
            connection.commit()
        monitor = self.get_monitor(task_id)
        if monitor is None:
            raise RuntimeError("Failed to persist monitoring task.")
        return monitor

    def get_monitor(self, task_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM monitors WHERE task_id = ?",
                (task_id,),
            ).fetchone()
        return _row_to_monitor(row) if row else None

    def list_monitors(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM monitors ORDER BY created_at DESC"
            ).fetchall()
        return [_row_to_monitor(row) for row in rows]

    def list_monitors_for_user(self, user_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM monitors
                WHERE user_id = ?
                   OR user_id IS NULL
                   OR user_id = ''
                ORDER BY created_at DESC
                """,
                (user_id,),
            ).fetchall()
        owned = [_row_to_monitor(row) for row in rows if row["user_id"] == user_id]
        if owned:
            return owned
        return [
            _row_to_monitor(row)
            for row in rows
            if not row["user_id"]
        ]

    def set_enabled(self, task_id: str, enabled: bool) -> dict[str, Any] | None:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE monitors
                SET enabled = ?, updated_at = ?
                WHERE task_id = ?
                """,
                (1 if enabled else 0, utc_now().isoformat(), task_id),
            )
            connection.commit()
            if cursor.rowcount == 0:
                return None
        return self.get_monitor(task_id)

    def delete_monitor(self, task_id: str) -> bool:
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT task_id FROM monitors WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            if existing is None:
                return False
            connection.execute(
                "DELETE FROM gmail_matches WHERE monitor_id = ?",
                (task_id,),
            )
            connection.execute(
                "DELETE FROM action_history WHERE monitor_id = ?",
                (task_id,),
            )
            connection.execute(
                "DELETE FROM alerts WHERE monitor_id = ?",
                (task_id,),
            )
            connection.execute(
                "DELETE FROM observations WHERE monitor_id = ?",
                (task_id,),
            )
            connection.execute(
                "DELETE FROM monitors WHERE task_id = ?",
                (task_id,),
            )
            connection.commit()
        return True

    def add_observation(
        self,
        monitor_id: str,
        *,
        content_hash: str,
        summary: str,
        meaningful_change: bool | None = None,
        reason: str | None = None,
        action_required: bool | None = None,
        change_status: str | None = None,
        agents: list[str] | None = None,
        agent_trace: list[dict[str, Any]] | None = None,
        observed_facts: list[str] | None = None,
        observed_fact_records: list[dict[str, Any]] | None = None,
        relevant_excerpt: str | None = None,
        title: str | None = None,
        fetch_method: str | None = None,
        source_url: str | None = None,
    ) -> dict[str, Any]:
        observation_id = str(uuid.uuid4())
        checked_at = utc_now().isoformat()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO observations (
                    observation_id, monitor_id, content_hash, summary, checked_at,
                    meaningful_change, reason, action_required, change_status,
                    agents, agent_trace, observed_facts, observed_fact_records,
                    relevant_excerpt, title, fetch_method, source_url
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    observation_id,
                    monitor_id,
                    content_hash,
                    summary,
                    checked_at,
                    None if meaningful_change is None else int(meaningful_change),
                    reason,
                    None if action_required is None else int(action_required),
                    change_status,
                    json.dumps(agents or []),
                    json.dumps(agent_trace or []),
                    json.dumps(observed_facts or []),
                    json.dumps(observed_fact_records or []),
                    relevant_excerpt,
                    title,
                    fetch_method,
                    source_url,
                ),
            )
            connection.commit()
        observation = self.get_observation(observation_id)
        if observation is None:
            raise RuntimeError("Failed to persist observation.")
        return observation

    def get_observation(self, observation_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM observations WHERE observation_id = ?",
                (observation_id,),
            ).fetchone()
        return _row_to_observation(row) if row else None

    def get_latest_observation(self, monitor_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM observations
                WHERE monitor_id = ?
                ORDER BY checked_at DESC
                LIMIT 1
                """,
                (monitor_id,),
            ).fetchone()
        return _row_to_observation(row) if row else None

    def list_observations(self, monitor_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM observations
                WHERE monitor_id = ?
                ORDER BY checked_at DESC
                """,
                (monitor_id,),
            ).fetchall()
        return [_row_to_observation(row) for row in rows]

    def update_after_check(
        self,
        task_id: str,
        *,
        previous_content: str | None,
        previous_content_hash: str | None,
        last_change: str | None,
        status: str,
        content_changed: bool = False,
    ) -> dict[str, Any] | None:
        now = utc_now().isoformat()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE monitors
                SET last_checked_at = ?,
                    previous_content = ?,
                    previous_content_hash = ?,
                    last_change = ?,
                    status = ?,
                    updated_at = ?,
                    last_changed_at = CASE WHEN ? THEN ? ELSE last_changed_at END
                WHERE task_id = ?
                """,
                (
                    now,
                    previous_content,
                    previous_content_hash,
                    last_change,
                    status,
                    now,
                    int(content_changed),
                    now,
                    task_id,
                ),
            )
            connection.commit()
        return self.get_monitor(task_id)

    def mark_checked(self, task_id: str) -> None:
        """Record that a check finished without replacing the stored snapshot."""
        now = utc_now().isoformat()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE monitors
                SET last_checked_at = ?, updated_at = ?
                WHERE task_id = ?
                """,
                (now, now, task_id),
            )
            connection.commit()

    def create_alert(
        self,
        monitor_id: str,
        *,
        content_hash: str,
        summary: str,
        reason: str,
        action_required: bool,
        status: str = "pending",
        action_type: str | None = None,
        human_loop_state: str | None = None,
        user_notification: str | None = None,
        notification_status: str | None = None,
        source: str = "website",
    ) -> dict[str, Any]:
        existing = self.get_alert_by_monitor_and_hash(monitor_id, content_hash)
        if existing is not None:
            return existing

        alert_id = str(uuid.uuid4())
        created_at = utc_now().isoformat()
        try:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO alerts (
                        alert_id, monitor_id, content_hash, summary, reason,
                        action_required, status, created_at, updated_at,
                        action_type, human_loop_state, user_notification,
                        notification_status, source
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        alert_id,
                        monitor_id,
                        content_hash,
                        summary,
                        reason,
                        int(action_required),
                        status,
                        created_at,
                        created_at,
                        action_type,
                        human_loop_state,
                        user_notification,
                        notification_status,
                        source,
                    ),
                )
                connection.commit()
        except sqlite3.IntegrityError:
            existing = self.get_alert_by_monitor_and_hash(monitor_id, content_hash)
            if existing is not None:
                return existing
            raise
        alert = self.get_alert(alert_id)
        if alert is None:
            raise RuntimeError("Failed to persist alert.")
        return alert

    def get_alert(self, alert_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM alerts WHERE alert_id = ?",
                (alert_id,),
            ).fetchone()
        return _row_to_alert(row) if row else None

    def get_alert_by_monitor_and_hash(
        self,
        monitor_id: str,
        content_hash: str,
    ) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM alerts
                WHERE monitor_id = ? AND content_hash = ?
                """,
                (monitor_id, content_hash),
            ).fetchone()
        return _row_to_alert(row) if row else None

    def get_pending_alert_for_monitor(self, monitor_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM alerts
                WHERE monitor_id = ? AND status = 'pending'
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (monitor_id,),
            ).fetchone()
        return _row_to_alert(row) if row else None

    def update_alert(
        self,
        alert_id: str,
        *,
        content_hash: str,
        summary: str,
        reason: str,
        action_required: bool,
        action_type: str | None = None,
        human_loop_state: str | None = None,
        user_notification: str | None = None,
    ) -> dict[str, Any] | None:
        existing = self.get_alert(alert_id)
        if existing is None:
            return None
        same_hash = self.get_alert_by_monitor_and_hash(
            existing["monitor_id"],
            content_hash,
        )
        if same_hash is not None and same_hash["alert_id"] != alert_id:
            return same_hash
        now = utc_now().isoformat()
        try:
            with self._connect() as connection:
                cursor = connection.execute(
                    """
                    UPDATE alerts
                    SET content_hash = ?, summary = ?, reason = ?,
                        action_required = ?, action_type = ?,
                        human_loop_state = ?, user_notification = ?,
                        updated_at = ?
                    WHERE alert_id = ?
                    """,
                    (
                        content_hash,
                        summary,
                        reason,
                        int(action_required),
                        action_type,
                        human_loop_state,
                        user_notification,
                        now,
                        alert_id,
                    ),
                )
                connection.commit()
                if cursor.rowcount == 0:
                    return None
        except sqlite3.IntegrityError:
            existing_hash = self.get_alert_by_monitor_and_hash(
                existing["monitor_id"],
                content_hash,
            )
            return existing_hash or existing
        return self.get_alert(alert_id)

    def list_alerts(self, status: str | None = None) -> list[dict[str, Any]]:
        with self._connect() as connection:
            if status:
                rows = connection.execute(
                    """
                    SELECT * FROM alerts
                    WHERE status = ?
                    ORDER BY created_at DESC
                    """,
                    (status,),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM alerts ORDER BY created_at DESC"
                ).fetchall()
        return [_row_to_alert(row) for row in rows]

    def set_alert_notification_status(
        self,
        alert_id: str,
        notification_status: str,
    ) -> dict[str, Any] | None:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE alerts
                SET notification_status = ?, updated_at = ?
                WHERE alert_id = ?
                """,
                (notification_status, utc_now().isoformat(), alert_id),
            )
            connection.commit()
            if cursor.rowcount == 0:
                return None
        return self.get_alert(alert_id)

    def add_action_history(
        self,
        monitor_id: str,
        *,
        action_type: str,
        human_loop_state: str,
        summary: str,
        alert_id: str | None = None,
    ) -> dict[str, Any]:
        action_id = str(uuid.uuid4())
        created_at = utc_now().isoformat()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO action_history (
                    action_id, monitor_id, alert_id, action_type,
                    human_loop_state, summary, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    action_id,
                    monitor_id,
                    alert_id,
                    action_type,
                    human_loop_state,
                    summary,
                    created_at,
                ),
            )
            connection.commit()
        record = self.get_action_history(action_id)
        if record is None:
            raise RuntimeError("Failed to persist action history.")
        return record

    def get_action_history(self, action_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM action_history WHERE action_id = ?",
                (action_id,),
            ).fetchone()
        return _row_to_action_history(row) if row else None

    def list_action_history(self, monitor_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM action_history
                WHERE monitor_id = ?
                ORDER BY created_at DESC
                """,
                (monitor_id,),
            ).fetchall()
        return [_row_to_action_history(row) for row in rows]

    def set_alert_status(self, alert_id: str, status: str) -> dict[str, Any] | None:
        if status == "dismissed":
            existing = self.get_alert(alert_id)
            if existing is None:
                return None
            if not self.delete_alert(alert_id):
                return None
            existing["status"] = "dismissed"
            existing["updated_at"] = utc_now()
            return existing
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE alerts
                SET status = ?, updated_at = ?
                WHERE alert_id = ?
                """,
                (status, utc_now().isoformat(), alert_id),
            )
            connection.commit()
            if cursor.rowcount == 0:
                return None
        return self.get_alert(alert_id)

    def delete_alert(self, alert_id: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM alerts WHERE alert_id = ?",
                (alert_id,),
            )
            connection.commit()
            return cursor.rowcount > 0

    def create_gmail_oauth_state(self, state: str, user_id: str) -> None:
        user_id = _require_gmail_user_id(user_id)
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO gmail_oauth_states (state, user_id, created_at) VALUES (?, ?, ?)",
                (state, user_id, utc_now().isoformat()),
            )
            connection.commit()

    def consume_gmail_oauth_state(self, state: str) -> str | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT created_at, user_id FROM gmail_oauth_states WHERE state = ?",
                (state,),
            ).fetchone()
            if row is None:
                return None
            created = datetime.fromisoformat(row["created_at"])
            user_id = str(row["user_id"] or "")
            connection.execute(
                "DELETE FROM gmail_oauth_states WHERE state = ?",
                (state,),
            )
            connection.commit()
        if created < utc_now() - OAUTH_STATE_TTL:
            return None
        return user_id or None

    def get_gmail_connection_by_email(self, google_email: str) -> dict[str, Any] | None:
        email = _normalize_google_email(google_email)
        if not email:
            return None
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM gmail_connections WHERE lower(google_email) = ?",
                (email,),
            ).fetchone()
        return _row_to_gmail_connection(row) if row else None

    def upsert_gmail_connection(
        self,
        *,
        user_id: str,
        google_email: str,
        token_blob: str,
        last_history_id: str | None,
        watch_expiration: datetime | None,
        status: str,
        error_message: str | None = None,
    ) -> dict[str, Any]:
        user_id = _require_gmail_user_id(user_id)
        google_email = _normalize_google_email(google_email)
        now = utc_now().isoformat()
        expiration = watch_expiration.isoformat() if watch_expiration else None
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT connected_at, created_at FROM gmail_connections WHERE user_id = ?",
                (user_id,),
            ).fetchone()
            if existing is None:
                connection.execute(
                    """
                    INSERT INTO gmail_connections (
                        user_id, google_email, token_blob, last_history_id,
                        watch_expiration, status, error_message, connected_at,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        user_id,
                        google_email,
                        token_blob,
                        last_history_id,
                        expiration,
                        status,
                        error_message,
                        now,
                        now,
                        now,
                    ),
                )
            else:
                connection.execute(
                    """
                    UPDATE gmail_connections
                    SET google_email = ?, token_blob = ?, last_history_id = ?,
                        watch_expiration = ?, status = ?, error_message = ?,
                        updated_at = ?
                    WHERE user_id = ?
                    """,
                    (
                        google_email,
                        token_blob,
                        last_history_id,
                        expiration,
                        status,
                        error_message,
                        now,
                        user_id,
                    ),
                )
            connection.commit()
        record = self.get_gmail_connection(user_id)
        if record is None:
            raise RuntimeError("Failed to persist Gmail connection.")
        return record

    def list_gmail_user_ids(self) -> list[str]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT user_id FROM gmail_connections ORDER BY connected_at"
            ).fetchall()
        return [str(row["user_id"]) for row in rows if row["user_id"]]

    def get_gmail_connection(self, user_id: str) -> dict[str, Any] | None:
        user_id = _require_gmail_user_id(user_id)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM gmail_connections WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        return _row_to_gmail_connection(row) if row else None

    def delete_gmail_connection(self, user_id: str) -> None:
        user_id = _require_gmail_user_id(user_id)
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM gmail_connections WHERE user_id = ?",
                (user_id,),
            )
            connection.execute(
                "DELETE FROM gmail_processed_messages WHERE user_id = ?",
                (user_id,),
            )
            connection.commit()

    def update_gmail_watch(
        self,
        *,
        user_id: str,
        last_history_id: str | None,
        watch_expiration: datetime | None,
        status: str,
        error_message: str | None = None,
    ) -> None:
        user_id = _require_gmail_user_id(user_id)
        expiration = watch_expiration.isoformat() if watch_expiration else None
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE gmail_connections
                SET last_history_id = ?, watch_expiration = ?, status = ?,
                    error_message = ?, updated_at = ?
                WHERE user_id = ?
                """,
                (
                    last_history_id,
                    expiration,
                    status,
                    error_message,
                    utc_now().isoformat(),
                    user_id,
                ),
            )
            connection.commit()

    def update_gmail_tokens(
        self,
        token_blob: str,
        user_id: str,
    ) -> None:
        user_id = _require_gmail_user_id(user_id)
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE gmail_connections
                SET token_blob = ?, updated_at = ?
                WHERE user_id = ?
                """,
                (token_blob, utc_now().isoformat(), user_id),
            )
            connection.commit()

    def is_gmail_message_processed(self, message_id: str, user_id: str) -> bool:
        user_id = _require_gmail_user_id(user_id)
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT 1 FROM gmail_processed_messages
                WHERE user_id = ? AND message_id = ?
                """,
                (user_id, message_id),
            ).fetchone()
        return row is not None

    def mark_gmail_message_processed(
        self,
        message_id: str,
        user_id: str,
    ) -> None:
        user_id = _require_gmail_user_id(user_id)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO gmail_processed_messages (user_id, message_id, processed_at)
                VALUES (?, ?, ?)
                """,
                (user_id, message_id, utc_now().isoformat()),
            )
            connection.commit()

    def touch_gmail_last_email(self, user_id: str) -> None:
        user_id = _require_gmail_user_id(user_id)
        now = utc_now().isoformat()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE gmail_connections
                SET last_email_received_at = ?, updated_at = ?
                WHERE user_id = ?
                """,
                (now, now, user_id),
            )
            connection.commit()

    def mark_gmail_monitor_matched(self, monitor_id: str) -> None:
        now = utc_now().isoformat()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE monitors
                SET last_changed_at = ?, updated_at = ?, last_change = ?, status = ?
                WHERE task_id = ?
                """,
                (now, now, "matched", "watching", monitor_id),
            )
            connection.commit()

    def add_gmail_match(
        self,
        *,
        monitor_id: str,
        user_id: str,
        message_id: str,
        alert_id: str | None,
        subject: str,
        sender: str,
        received_at: datetime | None,
        preview: str,
        reason: str,
        summary: str,
        action: str = "Alert user",
        relevant: bool = True,
    ) -> dict[str, Any]:
        user_id = _require_gmail_user_id(user_id)
        match_id = str(uuid.uuid4())
        created_at = utc_now().isoformat()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO gmail_matches (
                    match_id, monitor_id, user_id, message_id, alert_id,
                    subject, sender, received_at, preview, relevant,
                    reason, summary, action, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    match_id,
                    monitor_id,
                    user_id,
                    message_id,
                    alert_id,
                    subject,
                    sender,
                    received_at.isoformat() if received_at else None,
                    preview,
                    int(relevant),
                    reason,
                    summary,
                    action,
                    created_at,
                ),
            )
            connection.commit()
        return self.get_gmail_match(match_id) or {}

    def get_gmail_match(self, match_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM gmail_matches WHERE match_id = ?",
                (match_id,),
            ).fetchone()
        return _row_to_gmail_match(row) if row else None

    def list_gmail_matches(self, monitor_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM gmail_matches
                WHERE monitor_id = ?
                ORDER BY created_at DESC
                """,
                (monitor_id,),
            ).fetchall()
        return [_row_to_gmail_match(row) for row in rows]
