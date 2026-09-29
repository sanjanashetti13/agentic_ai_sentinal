import type { Alert, Monitor } from "../types";
import { formatDateTime, oneLine } from "../utils/format";
import { EmptyState } from "../components/EmptyState";

type AlertsPageProps = {
  alerts: Alert[];
  monitors: Monitor[];
  loading: boolean;
  loaded: boolean;
  updatingId: string | null;
  onStatus: (id: string, status: Alert["status"]) => Promise<void>;
  onOpenMonitor: (id: string) => void;
};

function gmailSourceLine(alert: Alert): string | null {
  if (alert.source !== "gmail") {
    return null;
  }
  const text = alert.user_notification || "";
  const marker = "Source:";
  const index = text.indexOf(marker);
  if (index >= 0) {
    return text.slice(index).trim();
  }
  return "Source: Gmail";
}

function AlertRow({
  alert,
  source,
  updatingId,
  onStatus,
  onOpenMonitor,
}: {
  alert: Alert;
  source: Monitor | undefined;
  updatingId: string | null;
  onStatus: AlertsPageProps["onStatus"];
  onOpenMonitor: (id: string) => void;
}) {
  const busy = updatingId === alert.alert_id;
  const summary = oneLine(alert.summary);
  const title =
    alert.source === "gmail" ? "Important email detected" : "Website changed";
  const sourceLine = gmailSourceLine(alert);
  return (
    <article
      className={`alert-row ${alert.status === "pending" ? "pending-alert" : ""}`}
    >
      <div className="alert-copy">
        <p className="alert-line">
          {source ? (
            <button
              className="linkish"
              type="button"
              onClick={() => onOpenMonitor(source.id)}
            >
              {title}
            </button>
          ) : (
            <strong>{title}</strong>
          )}
          <span className="muted">{formatDateTime(alert.created_at)}</span>
        </p>
        {summary ? <p className="alert-summary">{summary}</p> : null}
        {sourceLine ? <p className="muted">{sourceLine}</p> : null}
      </div>
      <div className="actions">
        <button
          className="primary"
          type="button"
          disabled={busy || alert.status === "acknowledged"}
          onClick={() => onStatus(alert.alert_id, "acknowledged")}
        >
          Acknowledge
        </button>
        <button
          className="secondary"
          type="button"
          disabled={busy || alert.status === "dismissed"}
          onClick={() => onStatus(alert.alert_id, "dismissed")}
        >
          Dismiss
        </button>
      </div>
    </article>
  );
}

export function AlertsPage({
  alerts,
  monitors,
  loading,
  loaded,
  updatingId,
  onStatus,
  onOpenMonitor,
}: AlertsPageProps) {
  const pending = alerts.filter((alert) => alert.status === "pending");
  const resolved = alerts.filter((alert) => alert.status === "acknowledged");
  const visible = pending.length + resolved.length;

  return (
    <section>
      <div className="page-header">
        <h2>Alerts</h2>
      </div>

      {loading && !loaded ? <p className="notice">Loading alerts...</p> : null}

      {loaded && visible === 0 ? (
        <EmptyState title="No alerts yet" />
      ) : (
        <>
          <div className="section">
            <h3>Pending</h3>
            {pending.length === 0 ? (
              <p className="empty">No pending alerts.</p>
            ) : (
              <div className="alert-list">
                {pending.map((alert) => (
                  <AlertRow
                    key={alert.alert_id}
                    alert={alert}
                    source={monitors.find(
                      (monitor) => monitor.id === alert.monitor_id,
                    )}
                    updatingId={updatingId}
                    onStatus={onStatus}
                    onOpenMonitor={onOpenMonitor}
                  />
                ))}
              </div>
            )}
          </div>
          <div className="section">
            <h3>Resolved</h3>
            {resolved.length === 0 ? (
              <p className="empty">No resolved alerts.</p>
            ) : (
              <div className="alert-list">
                {resolved.map((alert) => (
                  <AlertRow
                    key={alert.alert_id}
                    alert={alert}
                    source={monitors.find(
                      (monitor) => monitor.id === alert.monitor_id,
                    )}
                    updatingId={updatingId}
                    onStatus={onStatus}
                    onOpenMonitor={onOpenMonitor}
                  />
                ))}
              </div>
            )}
          </div>
        </>
      )}
    </section>
  );
}
