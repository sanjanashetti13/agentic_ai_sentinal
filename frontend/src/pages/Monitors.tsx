import { useEffect, useMemo, useState } from "react";
import { checkMonitor, deleteMonitor, getMonitor, updateMonitor } from "../api/monitors";
import { CheckResultCard } from "../components/CheckResultCard";
import { CreateMonitorForm } from "../components/CreateMonitorForm";
import { EmptyState } from "../components/EmptyState";
import { MonitorDetailPanel } from "../components/MonitorDetail";
import { MonitorList } from "../components/MonitorList";
import type {
  Alert,
  Monitor,
  MonitorCheckResult,
  MonitorDetail,
} from "../types";

type MonitorsPageProps = {
  monitors: Monitor[];
  alerts: Alert[];
  loading: boolean;
  loaded: boolean;
  focusId: string | null;
  startCreate: boolean;
  onConsumedFocus: () => void;
  onConsumedCreate: () => void;
  onRefresh: () => Promise<void>;
  onOpenAlerts?: () => void;
};

export function MonitorsPage({
  monitors,
  alerts,
  loading,
  loaded,
  focusId,
  startCreate,
  onConsumedFocus,
  onConsumedCreate,
  onRefresh,
  onOpenAlerts,
}: MonitorsPageProps) {
  const [showForm, setShowForm] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<MonitorDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [checkingId, setCheckingId] = useState<string | null>(null);
  const [togglingId, setTogglingId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [lastCheck, setLastCheck] = useState<MonitorCheckResult | null>(null);

  const alertCounts = useMemo(() => {
    const map: Record<string, number> = {};
    for (const alert of alerts) {
      map[alert.monitor_id] = (map[alert.monitor_id] ?? 0) + 1;
    }
    return map;
  }, [alerts]);

  async function loadDetail(id: string, silent = false) {
    if (!silent) {
      setDetailLoading(true);
    }
    setDetailError(null);
    try {
      const next = await getMonitor(id);
      setDetail(next);
    } catch (err) {
      if (!silent) {
        setDetail(null);
      }
      setDetailError(
        err instanceof Error
          ? err.message
          : "This monitor was not found or could not be loaded.",
      );
    } finally {
      setDetailLoading(false);
    }
  }

  async function handleSelect(id: string) {
    setSelectedId(id);
    setLastCheck(null);
    await loadDetail(id);
  }

  async function handleCheck(id: string) {
    if (checkingId) {
      return;
    }
    setSelectedId(id);
    setCheckingId(id);
    setDetailError(null);
    try {
      const result = await checkMonitor(id);
      setLastCheck(result);
      await Promise.all([loadDetail(id), onRefresh()]);
    } catch (err) {
      setLastCheck(null);
      setDetailError(
        err instanceof Error ? err.message : "The monitor check failed.",
      );
      try {
        await loadDetail(id);
      } catch {
        /* keep the check error */
      }
    } finally {
      setCheckingId(null);
    }
  }

  async function handleToggle(id: string, enabled: boolean) {
    setSelectedId(id);
    setTogglingId(id);
    setDetailError(null);
    try {
      await updateMonitor(id, { enabled });
      await Promise.all([loadDetail(id), onRefresh()]);
    } catch (err) {
      setDetailError(
        err instanceof Error ? err.message : "Could not update the monitor.",
      );
    } finally {
      setTogglingId(null);
    }
  }

  async function handleDelete(id: string) {
    if (deletingId) {
      return;
    }
    if (!window.confirm("Delete this monitor?")) {
      return;
    }
    setDeletingId(id);
    setDetailError(null);
    try {
      await deleteMonitor(id);
      if (selectedId === id) {
        setSelectedId(null);
        setDetail(null);
        setLastCheck(null);
      }
      await onRefresh();
    } catch (err) {
      setDetailError(
        err instanceof Error ? err.message : "Could not delete the monitor.",
      );
    } finally {
      setDeletingId(null);
    }
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
    setShowForm(true);
    onConsumedCreate();
  }, [startCreate, onConsumedCreate]);

  useEffect(() => {
    if (!selectedId) {
      return;
    }
    const timer = window.setInterval(() => {
      void loadDetail(selectedId, true);
    }, 4000);
    return () => window.clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId]);

  const showDetail = selectedId !== null;
  const showCheckResult =
    lastCheck &&
    selectedId === lastCheck.monitor_id &&
    (lastCheck.change_status === "changed" ||
      lastCheck.change_status === "blocked" ||
      lastCheck.change_status === "error");

  return (
    <section>
      <div className="page-header">
        <h2>Web Monitoring</h2>
        <button
          className="primary"
          type="button"
          onClick={() => setShowForm(true)}
        >
          + Create Monitor
        </button>
      </div>

      {loading && !loaded ? <p className="notice">Loading monitors...</p> : null}

      {showForm ? (
        <CreateMonitorForm
          onCreated={async (monitor) => {
            setShowForm(false);
            await onRefresh();
            await handleSelect(monitor.id);
          }}
          onCancel={() => setShowForm(false)}
        />
      ) : null}

      {loaded && monitors.length === 0 && !showForm ? (
        <EmptyState
          title="No monitors"
          action={{ label: "Create Monitor", onClick: () => setShowForm(true) }}
        />
      ) : null}

      {showCheckResult && lastCheck ? (
        <CheckResultCard
          result={lastCheck}
          onOpenAlert={lastCheck.alert_id ? onOpenAlerts : undefined}
        />
      ) : null}

      {detailError && !showDetail ? <p className="error">{detailError}</p> : null}

      <div className={`monitors-layout ${showDetail ? "with-detail" : ""}`}>
        <MonitorList
          monitors={monitors}
          alertCounts={alertCounts}
          selectedId={selectedId}
          checkingId={checkingId}
          togglingId={togglingId}
          deletingId={deletingId}
          onSelect={handleSelect}
          onCheck={handleCheck}
          onToggle={handleToggle}
          onDelete={handleDelete}
        />
        {showDetail ? (
          <MonitorDetailPanel
            detail={detail}
            alerts={alerts}
            lastCheck={
              lastCheck && selectedId === lastCheck.monitor_id ? lastCheck : null
            }
            loading={detailLoading}
            checking={checkingId === selectedId && checkingId !== null}
            toggling={togglingId === selectedId && togglingId !== null}
            deleting={deletingId === selectedId && deletingId !== null}
            error={detailError}
            onCheck={() => {
              if (selectedId) {
                void handleCheck(selectedId);
              }
            }}
            onToggle={(enabled) => {
              if (selectedId) {
                void handleToggle(selectedId, enabled);
              }
            }}
            onDelete={() => {
              if (selectedId) {
                void handleDelete(selectedId);
              }
            }}
            onClose={() => {
              setSelectedId(null);
              setDetail(null);
              setLastCheck(null);
              setDetailError(null);
            }}
          />
        ) : null}
      </div>
    </section>
  );
}
