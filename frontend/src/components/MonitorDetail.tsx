import type { Alert, MonitorCheckResult, MonitorDetail } from "../types";
import { formatDateTime, formatLastChecked, formatRelativeTime } from "../utils/format";
import { AgentTrace } from "./AgentTrace";
import { HumanLoopNotice } from "./HumanLoopNotice";
import { MonitorLogs } from "./MonitorLogs";
import { StatusBadge } from "./StatusBadge";

type MonitorDetailPanelProps = {
  detail: MonitorDetail | null;
  alerts: Alert[];
  lastCheck: MonitorCheckResult | null;
  loading: boolean;
  checking: boolean;
  toggling: boolean;
  deleting: boolean;
  error: string | null;
  onCheck: () => void;
  onToggle: (enabled: boolean) => void;
  onDelete: () => void;
  onClose: () => void;
};

export function MonitorDetailPanel({
  detail,
  alerts,
  lastCheck,
  loading,
  checking,
  toggling,
  deleting,
  error,
  onCheck,
  onToggle,
  onDelete,
  onClose,
}: MonitorDetailPanelProps) {
  if (loading && !detail) {
    return <p className="notice">Loading details...</p>;
  }

  if (!detail) {
    return null;
  }

  const latest = detail.latest_observation;
  const matchingAlert = latest
    ? alerts.find(
        (alert) =>
          alert.monitor_id === detail.id &&
          alert.content_hash === latest.content_hash,
      )
    : undefined;
  const checkedAt = latest?.checked_at ?? detail.last_checked_at;
  const traceEntries = lastCheck?.agent_trace ?? latest?.agent_trace;
  const traceStatus = lastCheck?.change_status ?? latest?.change_status;
  const hitlState =
    lastCheck?.human_loop_state ?? matchingAlert?.human_loop_state ?? null;
  const monitorAlerts = alerts.filter((alert) => alert.monitor_id === detail.id);

  return (
    <section className="detail-panel">
      <div className="page-header">
        <h3>Details</h3>
        <button className="secondary" type="button" onClick={onClose}>
          Close
        </button>
      </div>
      <dl className="detail-list">
        <dt>Goal</dt>
        <dd>{detail.goal}</dd>
        <dt>URL</dt>
        <dd>
          <a href={detail.url} target="_blank" rel="noreferrer">
            {detail.url}
          </a>
        </dd>
        <dt>Status</dt>
        <dd>
          <StatusBadge
            lastChange={detail.last_change}
            lastCheckedAt={detail.last_checked_at}
            checking={checking}
            enabled={detail.enabled}
            meaningful={latest?.meaningful_change ?? lastCheck?.meaningful_change}
          />
          {detail.enabled ? " · Enabled" : " · Disabled"}
        </dd>
        <dt>Last checked</dt>
        <dd>
          {formatLastChecked(checkedAt)}
          {checkedAt ? ` · ${formatDateTime(checkedAt)}` : ""}
        </dd>
        <dt>Last changed</dt>
        <dd>{formatRelativeTime(detail.last_changed_at)}</dd>
      </dl>
      <HumanLoopNotice state={hitlState} />
      {error ? <p className="error">{error}</p> : null}
      <div className="actions">
        <button
          className="primary"
          type="button"
          onClick={onCheck}
          disabled={checking || toggling || deleting || !detail.enabled}
        >
          {checking ? "Checking..." : "Check now"}
        </button>
        <button
          className="secondary"
          type="button"
          onClick={() => onToggle(!detail.enabled)}
          disabled={toggling || checking || deleting}
        >
          {toggling ? "Updating..." : detail.enabled ? "Disable" : "Enable"}
        </button>
        <button
          className="danger"
          type="button"
          onClick={onDelete}
          disabled={checking || toggling || deleting}
        >
          {deleting ? "Deleting..." : "Delete"}
        </button>
      </div>
      <div className="section tight">
        <h3>Logs</h3>
        <MonitorLogs observations={detail.observations ?? []} alerts={monitorAlerts} />
      </div>
      <div className="section tight">
        <h3>Agent Activity</h3>
        <AgentTrace entries={traceEntries} changeStatus={traceStatus} />
      </div>
    </section>
  );
}
