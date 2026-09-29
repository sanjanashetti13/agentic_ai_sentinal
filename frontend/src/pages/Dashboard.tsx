import {
  Activity,
  Bell,
  ChevronRight,
  Globe2,
  Mail,
  RefreshCw,
} from "lucide-react";
import type { Alert, Monitor, SystemStatus } from "../types";
import { formatLastChecked, formatRelativeTime } from "../utils/format";
import { isGmailMonitor, isWebsiteMonitor } from "../utils/views";
import { EmptyState } from "../components/EmptyState";
import { SchedulerStatus } from "../components/SchedulerStatus";
import { StatusBadge } from "../components/StatusBadge";

type DashboardProps = {
  monitors: Monitor[];
  alerts: Alert[];
  loading: boolean;
  loaded: boolean;
  onOpenMonitor: (id: string) => void;
  onCreateMonitor: () => void;
  onCreateGmailMonitor: () => void;
  systemStatus?: SystemStatus | null;
};

function MonitorStatusList({
  monitors,
  onOpenMonitor,
}: {
  monitors: Monitor[];
  onOpenMonitor: (id: string) => void;
}) {
  return (
    <div className="monitor-status-list">
      {monitors.map((monitor) => {
        const gmail = isGmailMonitor(monitor);
        return (
          <button
            key={monitor.id}
            type="button"
            className="monitor-status-card"
            onClick={() => onOpenMonitor(monitor.id)}
          >
            <span
              className={`monitor-kind-icon ${gmail ? "gmail" : "web"}`}
              aria-hidden="true"
            >
              {gmail ? <Mail className="h-5 w-5" /> : <Globe2 className="h-5 w-5" />}
            </span>
            <span className="monitor-status-body">
              <span className="monitor-status-top">
                <span className="monitor-goal">{monitor.goal}</span>
                <span className={`type-badge ${gmail ? "gmail" : "web"}`}>
                  {gmail ? "Gmail" : "Web"}
                </span>
              </span>
              <span className="monitor-status-bottom">
                <StatusBadge
                  lastChange={monitor.last_change}
                  lastCheckedAt={monitor.last_checked_at}
                  enabled={monitor.enabled}
                />
                <span className="muted">
                  Last checked:{" "}
                  {gmail
                    ? formatRelativeTime(monitor.last_checked_at)
                    : formatLastChecked(monitor.last_checked_at)}
                </span>
              </span>
            </span>
            <ChevronRight className="monitor-arrow h-5 w-5" aria-hidden="true" />
          </button>
        );
      })}
    </div>
  );
}

export function Dashboard({
  monitors,
  alerts,
  loading,
  loaded,
  onOpenMonitor,
  onCreateMonitor,
  onCreateGmailMonitor,
  systemStatus,
}: DashboardProps) {
  const webMonitors = monitors.filter(isWebsiteMonitor);
  const gmailMonitors = monitors.filter(isGmailMonitor);
  const listedMonitors = [...webMonitors, ...gmailMonitors];
  const total = monitors.length;
  const active = monitors.filter((monitor) => monitor.enabled).length;
  const changes = monitors.filter((monitor) => Boolean(monitor.last_changed_at))
    .length;
  const pendingAlerts = alerts.filter((alert) => alert.status === "pending");

  return (
    <section>
      <div className="page-header">
        <h2>Dashboard</h2>
      </div>

      <SchedulerStatus status={systemStatus} />

      {loading && !loaded ? <p className="notice">Loading...</p> : null}

      {loaded && total === 0 ? (
        <EmptyState
          title="No monitors"
          action={{ label: "Create monitor", onClick: onCreateMonitor }}
        >
          Add a website or Gmail monitor to start.
        </EmptyState>
      ) : null}

      <div className="summary-row">
        <div className="summary-cell accent-blue">
          <span className="summary-icon" aria-hidden="true">
            <Globe2 className="h-6 w-6" />
          </span>
          <div className="summary-copy">
            <span>Monitors</span>
            <strong>{loaded ? total : "—"}</strong>
          </div>
        </div>
        <div className="summary-cell accent-teal">
          <span className="summary-icon" aria-hidden="true">
            <Activity className="h-6 w-6" />
          </span>
          <div className="summary-copy">
            <span>Active</span>
            <strong>{loaded ? active : "—"}</strong>
          </div>
        </div>
        <div className="summary-cell accent-gold">
          <span className="summary-icon" aria-hidden="true">
            <RefreshCw className="h-6 w-6" />
          </span>
          <div className="summary-copy">
            <span>Changes</span>
            <strong>{loaded ? changes : "—"}</strong>
          </div>
        </div>
        <div className="summary-cell accent-purple">
          <span className="summary-icon" aria-hidden="true">
            <Bell className="h-6 w-6" />
          </span>
          <div className="summary-copy">
            <span>Alerts</span>
            <strong>{loaded ? pendingAlerts.length : "—"}</strong>
          </div>
        </div>
      </div>

      {loaded && total > 0 ? (
        <div className="section">
          <h3 className="monitors-heading">Monitors</h3>
          {listedMonitors.length > 0 ? (
            <MonitorStatusList
              monitors={listedMonitors}
              onOpenMonitor={onOpenMonitor}
            />
          ) : null}
          {webMonitors.length === 0 ? (
            <p className="muted">
              No website monitors.{" "}
              <button className="linkish" type="button" onClick={onCreateMonitor}>
                Create one
              </button>
            </p>
          ) : null}
          {gmailMonitors.length === 0 ? (
            <p className="muted">
              No Gmail monitors.{" "}
              <button
                className="linkish"
                type="button"
                onClick={onCreateGmailMonitor}
              >
                Create one
              </button>
            </p>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
