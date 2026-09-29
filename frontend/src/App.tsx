import { useCallback, useEffect, useMemo, useState } from "react";
import { getAlerts, updateAlertStatus } from "./api/alerts";
import { getGmailStatus, type GmailStatusResponse } from "./api/gmail";
import { getHealth, getSystemStatus } from "./api/health";
import { getMonitors } from "./api/monitors";
import { AppShell } from "./components/AppShell";
import { AlertsPage } from "./pages/Alerts";
import { Dashboard } from "./pages/Dashboard";
import { GmailMonitorsPage } from "./pages/GmailMonitors";
import { IntegrationsPage } from "./pages/Integrations";
import { MonitorsPage } from "./pages/Monitors";
import type { Alert, AlertStatus, Monitor, SystemStatus } from "./types";
import {
  isGmailMonitor,
  isWebsiteMonitor,
  VIEW_PATHS,
  viewFromPath,
  type AppView,
} from "./utils/views";
import "./App.css";

export default function App() {
  const [view, setView] = useState<AppView>(() =>
    viewFromPath(window.location.pathname),
  );
  const [monitors, setMonitors] = useState<Monitor[]>([]);
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [loading, setLoading] = useState(true);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [updatingAlertId, setUpdatingAlertId] = useState<string | null>(null);
  const [focusMonitorId, setFocusMonitorId] = useState<string | null>(null);
  const [startCreate, setStartCreate] = useState(false);
  const [startGmailCreate, setStartGmailCreate] = useState(false);
  const [systemStatus, setSystemStatus] = useState<SystemStatus | null>(null);
  const [gmailStatus, setGmailStatus] = useState<GmailStatusResponse | null>(null);
  const [seenAlertIds, setSeenAlertIds] = useState<Set<string>>(() => new Set());

  const websiteMonitors = useMemo(
    () => monitors.filter(isWebsiteMonitor),
    [monitors],
  );
  const gmailMonitors = useMemo(
    () => monitors.filter(isGmailMonitor),
    [monitors],
  );

  const refresh = useCallback(async () => {
    await getHealth();
    const [nextMonitors, nextAlerts, nextStatus, nextGmail] = await Promise.all([
      getMonitors(),
      getAlerts(),
      getSystemStatus().catch(() => null),
      getGmailStatus().catch(() => null),
    ]);
    setMonitors(nextMonitors);
    setAlerts(nextAlerts);
    setSystemStatus(nextStatus);
    setGmailStatus(nextGmail);
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      await refresh();
      setError(null);
      setLoaded(true);
    } catch (err: unknown) {
      setError(
        err instanceof Error
          ? err.message
          : "Could not load data from the API.",
      );
    } finally {
      setLoading(false);
    }
  }, [refresh]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    function onPopState() {
      setView(viewFromPath(window.location.pathname));
    }
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const gmail = params.get("gmail");
    if (!gmail) {
      return;
    }
    window.history.replaceState({}, "", window.location.pathname);
    if (gmail === "error") {
      setError("Gmail connection failed. Try Connect Gmail again.");
    }
    if (gmail === "connected") {
      setView("gmail");
      const path = VIEW_PATHS.gmail;
      if (window.location.pathname !== path) {
        window.history.replaceState({}, "", path);
      }
    }
    void refresh();
  }, [refresh]);

  useEffect(() => {
    if (!loaded) {
      return;
    }
    const timer = window.setInterval(() => {
      void refresh();
    }, 4000);
    return () => window.clearInterval(timer);
  }, [loaded, refresh]);

  function navigate(next: AppView) {
    const path = VIEW_PATHS[next];
    if (window.location.pathname !== path) {
      window.history.pushState({}, "", path);
    }
    setView(next);
  }

  function openMonitor(monitorId?: string) {
    const monitor = monitors.find((item) => item.id === monitorId);
    if (monitor && isGmailMonitor(monitor)) {
      if (monitorId) {
        setFocusMonitorId(monitorId);
      }
      navigate("gmail");
      return;
    }
    if (monitorId) {
      setFocusMonitorId(monitorId);
    }
    navigate("monitors");
  }

  function markPendingAlertsSeen(list: Alert[] = alerts) {
    setSeenAlertIds((prev) => {
      const next = new Set(prev);
      let changed = false;
      for (const alert of list) {
        if (alert.status === "pending" && !next.has(alert.alert_id)) {
          next.add(alert.alert_id);
          changed = true;
        }
      }
      return changed ? next : prev;
    });
  }

  function handleNavigate(next: AppView) {
    if (next === "alerts") {
      markPendingAlertsSeen();
    }
    navigate(next);
  }

  useEffect(() => {
    if (view === "alerts") {
      markPendingAlertsSeen();
    }
  }, [view, alerts]);

  async function handleAlertStatus(id: string, status: AlertStatus) {
    setUpdatingAlertId(id);
    try {
      await updateAlertStatus(id, status);
      await refresh();
      setError(null);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Could not update the alert.",
      );
    } finally {
      setUpdatingAlertId(null);
    }
  }

  const pendingCount = alerts.filter(
    (alert) => alert.status === "pending" && !seenAlertIds.has(alert.alert_id),
  ).length;

  return (
    <AppShell
      current={view}
      pendingAlerts={pendingCount}
      onNavigate={handleNavigate}
    >
      {error ? (
        <div className="error banner">
          <div>
            <strong>Could not complete the request.</strong>
            <p>{error}</p>
          </div>
          <button className="secondary" type="button" onClick={() => void load()}>
            Retry
          </button>
        </div>
      ) : null}

      {!loaded && !loading && error ? (
        <p className="empty">
          The Sentinel API is unavailable. Start FastAPI on port 8000 and
          retry.
        </p>
      ) : view === "dashboard" ? (
        <Dashboard
          monitors={monitors}
          alerts={alerts}
          loading={loading}
          loaded={loaded}
          onOpenMonitor={(id) => openMonitor(id)}
          onCreateMonitor={() => {
            setStartCreate(true);
            navigate("monitors");
          }}
          onCreateGmailMonitor={() => {
            setStartGmailCreate(true);
            navigate("gmail");
          }}
          systemStatus={systemStatus}
        />
      ) : view === "alerts" ? (
        <AlertsPage
          alerts={alerts}
          monitors={monitors}
          loading={loading}
          loaded={loaded}
          updatingId={updatingAlertId}
          onStatus={handleAlertStatus}
          onOpenMonitor={(id) => openMonitor(id)}
        />
      ) : view === "gmail" ? (
        <GmailMonitorsPage
          monitors={gmailMonitors}
          alerts={alerts.filter((alert) => alert.source === "gmail")}
          loading={loading}
          loaded={loaded}
          gmailStatus={gmailStatus}
          focusId={view === "gmail" ? focusMonitorId : null}
          startCreate={startGmailCreate}
          onConsumedFocus={() => setFocusMonitorId(null)}
          onConsumedCreate={() => setStartGmailCreate(false)}
          onRefresh={async () => {
            try {
              await refresh();
              setError(null);
              setLoaded(true);
            } catch (err) {
              setError(
                err instanceof Error
                  ? err.message
                  : "Could not refresh Gmail monitors.",
              );
            }
          }}
          onOpenAlert={() => handleNavigate("alerts")}
        />
      ) : view === "integrations" ? (
        <IntegrationsPage
          gmailStatus={gmailStatus}
          onRefreshGmail={async () => {
            await refresh();
          }}
        />
      ) : (
        <MonitorsPage
          monitors={websiteMonitors}
          alerts={alerts}
          loading={loading}
          loaded={loaded}
          focusId={view === "monitors" ? focusMonitorId : null}
          startCreate={startCreate}
          onConsumedFocus={() => setFocusMonitorId(null)}
          onConsumedCreate={() => setStartCreate(false)}
          onRefresh={async () => {
            try {
              await refresh();
              setError(null);
              setLoaded(true);
            } catch (err) {
              setError(
                err instanceof Error
                  ? err.message
                  : "Could not refresh monitors.",
              );
            }
          }}
          onOpenAlerts={() => handleNavigate("alerts")}
        />
      )}
    </AppShell>
  );
}
