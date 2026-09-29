import { useEffect, useMemo, useState } from "react";
import { deleteMonitor, getMonitor, updateMonitor } from "../api/monitors";
import type { GmailStatusResponse } from "../api/gmail";
import { disconnectGmail, startGmailConnect } from "../api/gmail";
import { CreateGmailMonitorForm } from "../components/CreateGmailMonitorForm";
import { EmptyState } from "../components/EmptyState";
import type { Alert, GmailMatchedEmail, Monitor, MonitorDetail } from "../types";
import { formatDateTime, formatRelativeTime } from "../utils/format";

type GmailMonitorsPageProps = {
  monitors: Monitor[];
  alerts: Alert[];
  loading: boolean;
  loaded: boolean;
  gmailStatus: GmailStatusResponse | null;
  focusId: string | null;
  startCreate: boolean;
  onConsumedFocus: () => void;
  onConsumedCreate: () => void;
  onRefresh: () => Promise<void>;
  onOpenAlert: (alertId?: string) => void;
};

function isConnected(status: GmailStatusResponse | null) {
  return (
    status?.status === "CONNECTED" ||
    status?.status === "WATCH_ACTIVE" ||
    status?.status === "WATCH_EXPIRED" ||
    status?.status === "ERROR"
  );
}

function statusLabel(status: GmailStatusResponse | null) {
  switch (status?.status) {
    case "WATCH_ACTIVE":
    case "CONNECTED":
      return "Active";
    case "WATCH_EXPIRED":
      return "Watch expired";
    case "ERROR":
      return "Error";
    case "CONNECTING":
      return "Connecting";
    default:
      return "Not connected";
  }
}

function monitorTitle(monitor: Monitor) {
  return monitor.name?.trim() || monitor.goal;
}

export function GmailMonitorsPage({
  monitors,
  alerts,
  loading,
  loaded,
  gmailStatus,
  focusId,
  startCreate,
  onConsumedFocus,
  onConsumedCreate,
  onRefresh,
  onOpenAlert,
}: GmailMonitorsPageProps) {
  const [showCreate, setShowCreate] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<MonitorDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [connecting, setConnecting] = useState(false);
  const connected = isConnected(gmailStatus);

  const alertCounts = useMemo(() => {
    const map: Record<string, number> = {};
    for (const alert of alerts) {
      map[alert.monitor_id] = (map[alert.monitor_id] ?? 0) + 1;
    }
    return map;
  }, [alerts]);

  async function loadDetail(id: string) {
    setDetailLoading(true);
    setError(null);
    try {
      setDetail(await getMonitor(id));
    } catch (err) {
      setDetail(null);
      setError(
        err instanceof Error ? err.message : "Could not load this Gmail monitor.",
      );
    } finally {
      setDetailLoading(false);
    }
  }

  async function handleSelect(id: string) {
    setSelectedId(id);
    await loadDetail(id);
  }

  useEffect(() => {
    if (!focusId) {
      return;
    }
    void handleSelect(focusId).then(onConsumedFocus);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focusId]);

  useEffect(() => {
    if (!startCreate) {
      return;
    }
    setShowCreate(true);
    onConsumedCreate();
  }, [startCreate, onConsumedCreate]);

  useEffect(() => {
    if (!selectedId) {
      return;
    }
    const timer = window.setInterval(() => {
      void loadDetail(selectedId);
    }, 4000);
    return () => window.clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId]);

  async function handleToggle(id: string, enabled: boolean) {
    setBusyId(id);
    setError(null);
    try {
      await updateMonitor(id, { enabled });
      await onRefresh();
      if (selectedId === id) {
        await loadDetail(id);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not update the monitor.");
    } finally {
      setBusyId(null);
    }
  }

  async function handleDelete(id: string) {
    if (!window.confirm("Delete this Gmail monitor?")) {
      return;
    }
    setBusyId(id);
    setError(null);
    try {
      await deleteMonitor(id);
      if (selectedId === id) {
        setSelectedId(null);
        setDetail(null);
      }
      await onRefresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not delete the monitor.");
    } finally {
      setBusyId(null);
    }
  }

  async function handleDisconnect() {
    setBusyId("disconnect");
    try {
      await disconnectGmail();
      await onRefresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not disconnect Gmail.");
    } finally {
      setBusyId(null);
    }
  }

  async function handleConnect() {
    setConnecting(true);
    try {
      const result = await startGmailConnect();
      window.location.assign(result.authorization_url);
    } catch (err) {
      setConnecting(false);
      setError(
        err instanceof Error ? err.message : "Could not start Gmail authorization.",
      );
    }
  }

  if (selectedId) {
    const matches = detail?.matched_emails ?? [];
    const latestMatch = matches[0];
    return (
      <section>
        <div className="page-header">
          <button
            className="secondary"
            type="button"
            onClick={() => {
              setSelectedId(null);
              setDetail(null);
            }}
          >
            Back
          </button>
        </div>
        {detailLoading && !detail ? <p className="notice">Loading monitor...</p> : null}
        {error ? <p className="error">{error}</p> : null}
        {detail ? (
          <div className="gmail-detail">
            <header className="gmail-detail-head">
              <div>
                <h2>{monitorTitle(detail)}</h2>
                <p className={`watch-pill ${detail.enabled ? "on" : "off"}`}>
                  <span className="status-dot" />
                  {detail.enabled ? "Monitoring" : "Paused"}
                </p>
              </div>
            </header>
            <div className="gmail-meta-grid">
              <article>
                <span>Goal</span>
                <p>{detail.goal}</p>
              </article>
              <article>
                <span>Status</span>
                <p>Watching</p>
              </article>
              <article>
                <span>Last email received</span>
                <p>{formatRelativeTime(detail.last_email_received_at)}</p>
              </article>
              <article>
                <span>Last relevant email</span>
                <p>
                  {formatRelativeTime(
                    latestMatch?.received_at || latestMatch?.created_at,
                  )}
                </p>
              </article>
              <article>
                <span>Alerts generated</span>
                <p>{alertCounts[detail.id] ?? 0}</p>
              </article>
            </div>
            <h3>Matched emails</h3>
            {matches.length === 0 ? (
              <p className="muted">No relevant emails have matched this goal yet.</p>
            ) : (
              <div className="matched-list">
                {matches.map((item) => (
                  <MatchedEmailCard
                    key={item.id}
                    item={item}
                    onOpenAlert={onOpenAlert}
                  />
                ))}
              </div>
            )}
          </div>
        ) : null}
      </section>
    );
  }

  return (
    <section>
      <div className="page-header">
        <div>
          <h2>Gmail Monitoring</h2>
          <p className="muted gmail-connection-line">
            {connected && gmailStatus?.google_email ? (
              <>
                Connected as {gmailStatus.google_email}
                <span className={`watch-pill ${gmailStatus.status === "ERROR" ? "off" : "on"}`}>
                  <span className="status-dot" />
                  {statusLabel(gmailStatus)}
                </span>
              </>
            ) : (
              <>Status: {statusLabel(gmailStatus)}</>
            )}
          </p>
          <p className="muted">
            Event-driven: Gmail → Pub/Sub → Monitoring → Analysis → Action.
          </p>
        </div>
        <div className="actions">
          {connected ? (
            <button
              className="secondary"
              type="button"
              disabled={busyId === "disconnect"}
              onClick={() => void handleDisconnect()}
            >
              Disconnect
            </button>
          ) : (
            <button
              className="secondary"
              type="button"
              disabled={connecting || gmailStatus?.configured === false}
              onClick={() => void handleConnect()}
            >
              Connect Gmail
            </button>
          )}
          <button
            className="primary"
            type="button"
            onClick={() => setShowCreate(true)}
          >
            + Create Gmail Monitor
          </button>
        </div>
      </div>

      {loading && !loaded ? <p className="notice">Loading Gmail monitors...</p> : null}
      {error ? <p className="error">{error}</p> : null}

      {loaded && monitors.length === 0 ? (
        <EmptyState
          title="No Gmail monitors"
          action={{
            label: "Create Gmail Monitor",
            onClick: () => setShowCreate(true),
          }}
        >
          Describe a natural-language goal. Sentinel will watch incoming mail
          through the existing Gmail integration.
        </EmptyState>
      ) : (
        <div className="gmail-card-grid">
          {monitors.map((monitor) => {
            const count = alertCounts[monitor.id] ?? 0;
            return (
              <article key={monitor.id} className="gmail-monitor-card">
                <div className="gmail-card-top">
                  <h3>{monitorTitle(monitor)}</h3>
                  <p className={`watch-pill ${monitor.enabled ? "on" : "off"}`}>
                    <span className="status-dot" />
                    {monitor.enabled ? "Active" : "Paused"}
                  </p>
                </div>
                <p className="gmail-goal">“{monitor.goal}”</p>
                <div className="monitor-meta">
                  <span className="muted">
                    Last relevant email: {formatRelativeTime(monitor.last_changed_at)}
                  </span>
                  <span className="muted">
                    Alerts: {count}
                  </span>
                </div>
                <div className="monitor-actions">
                  <button
                    className="primary"
                    type="button"
                    onClick={() => void handleSelect(monitor.id)}
                  >
                    View Details
                  </button>
                  <button
                    className="secondary"
                    type="button"
                    disabled={busyId === monitor.id}
                    onClick={() => void handleToggle(monitor.id, !monitor.enabled)}
                  >
                    {monitor.enabled ? "Pause" : "Enable"}
                  </button>
                  <button
                    className="danger"
                    type="button"
                    disabled={busyId === monitor.id}
                    onClick={() => void handleDelete(monitor.id)}
                  >
                    Delete
                  </button>
                </div>
              </article>
            );
          })}
        </div>
      )}

      {showCreate ? (
        <CreateGmailMonitorForm
          onCreated={async (monitor) => {
            setShowCreate(false);
            await onRefresh();
            await handleSelect(monitor.id);
          }}
          onCancel={() => setShowCreate(false)}
        />
      ) : null}
    </section>
  );
}

function MatchedEmailCard({
  item,
  onOpenAlert,
}: {
  item: GmailMatchedEmail;
  onOpenAlert: (alertId?: string) => void;
}) {
  return (
    <article className="matched-email">
      <div className="matched-copy">
        <h4>{item.subject || "(no subject)"}</h4>
        <p className="muted">
          {item.sender}
          {item.received_at ? ` · ${formatDateTime(item.received_at)}` : ""}
        </p>
        {item.preview ? <p className="email-preview">{item.preview}</p> : null}
        <p className={`watch-pill ${item.relevant ? "on" : "off"}`}>
          <span className="status-dot" />
          {item.relevant ? "Relevant" : "Ignored"}
        </p>
        {item.reason ? (
          <div className="agent-decision">
            <strong>Agent Decision</strong>
            <p>✓ {item.relevant ? "Relevant" : "Not relevant"}</p>
            <p className="muted">Reason: {item.reason}</p>
            <p className="muted">Action: {item.action}</p>
          </div>
        ) : null}
      </div>
      {item.alert_id ? (
        <button
          className="secondary"
          type="button"
          onClick={() => onOpenAlert(item.alert_id ?? undefined)}
        >
          View Alert
        </button>
      ) : null}
    </article>
  );
}
