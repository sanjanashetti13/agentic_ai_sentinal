import type { Monitor } from "../types";
import { formatLastChecked, formatRelativeTime } from "../utils/format";
import { EnabledBadge, StatusBadge } from "./StatusBadge";

type MonitorListProps = {
  monitors: Monitor[];
  alertCounts: Record<string, number>;
  selectedId: string | null;
  checkingId: string | null;
  togglingId: string | null;
  deletingId: string | null;
  onSelect: (id: string) => void;
  onCheck: (id: string) => void;
  onToggle: (id: string, enabled: boolean) => void;
  onDelete: (id: string) => void;
};

export function MonitorList({
  monitors,
  alertCounts,
  selectedId,
  checkingId,
  togglingId,
  deletingId,
  onSelect,
  onCheck,
  onToggle,
  onDelete,
}: MonitorListProps) {
  if (monitors.length === 0) {
    return null;
  }

  return (
    <div className="monitor-list">
      {monitors.map((monitor) => {
        const busy =
          checkingId === monitor.id ||
          togglingId === monitor.id ||
          deletingId === monitor.id;
        const alerts = alertCounts[monitor.id] ?? 0;
        return (
          <article
            key={monitor.id}
            className={`monitor-item ${selectedId === monitor.id ? "selected" : ""}`}
          >
            <h3>{monitor.goal}</h3>
            <p className="monitor-url">{monitor.url}</p>
            <div className="monitor-meta">
              <EnabledBadge enabled={monitor.enabled} />
              <StatusBadge
                lastChange={monitor.last_change}
                lastCheckedAt={monitor.last_checked_at}
                checking={checkingId === monitor.id}
              />
              <span className="muted">
                Last checked: {formatLastChecked(monitor.last_checked_at)}
              </span>
              <span className="muted">
                Last changed: {formatRelativeTime(monitor.last_changed_at)}
              </span>
              {alerts > 0 ? (
                <span className="muted">
                  {alerts} alert{alerts === 1 ? "" : "s"}
                </span>
              ) : null}
            </div>
            <div className="monitor-actions">
              <button
                className="primary"
                type="button"
                disabled={busy || !monitor.enabled}
                onClick={() => onCheck(monitor.id)}
              >
                {checkingId === monitor.id ? "Checking..." : "Check now"}
              </button>
              <button
                className="secondary"
                type="button"
                disabled={busy}
                onClick={() => onToggle(monitor.id, !monitor.enabled)}
              >
                {togglingId === monitor.id
                  ? "Updating..."
                  : monitor.enabled
                    ? "Disable"
                    : "Enable"}
              </button>
              <button
                className="secondary"
                type="button"
                onClick={() => onSelect(monitor.id)}
              >
                Details
              </button>
              <button
                className="danger"
                type="button"
                disabled={busy}
                onClick={() => onDelete(monitor.id)}
              >
                {deletingId === monitor.id ? "Deleting..." : "Delete"}
              </button>
            </div>
          </article>
        );
      })}
    </div>
  );
}
