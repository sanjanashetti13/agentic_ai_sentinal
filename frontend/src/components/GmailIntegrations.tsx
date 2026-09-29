import { useState } from "react";
import {
  disconnectGmail,
  startGmailConnect,
  type GmailStatusResponse,
} from "../api/gmail";

type GmailIntegrationsProps = {
  status: GmailStatusResponse | null;
  onRefresh: () => Promise<void>;
};

function statusLabel(status: GmailStatusResponse | null, connecting: boolean) {
  if (connecting) {
    return "Connecting";
  }
  switch (status?.status) {
    case "WATCH_ACTIVE":
    case "CONNECTED":
      return "Active";
    case "WATCH_EXPIRED":
      return "Watch expired";
    case "ERROR":
      return "Error";
    case "DISCONNECTED":
      return "Disconnected";
    case "CONNECTING":
      return "Connecting";
    default:
      return "Not connected";
  }
}

function isConnected(status: GmailStatusResponse | null) {
  return (
    status?.status === "CONNECTED" ||
    status?.status === "WATCH_ACTIVE" ||
    status?.status === "WATCH_EXPIRED" ||
    status?.status === "ERROR"
  );
}

export function GmailIntegrations({
  status,
  onRefresh,
}: GmailIntegrationsProps) {
  const [busy, setBusy] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const connected = isConnected(status);

  async function handleConnect() {
    setBusy(true);
    setConnecting(true);
    setError(null);
    try {
      const result = await startGmailConnect();
      window.location.assign(result.authorization_url);
    } catch (err) {
      setConnecting(false);
      setError(
        err instanceof Error
          ? err.message
          : "Could not start Gmail authorization.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function handleDisconnect() {
    setBusy(true);
    setError(null);
    try {
      await disconnectGmail();
      await onRefresh();
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Could not disconnect Gmail.",
      );
    } finally {
      setBusy(false);
    }
  }

    return (
    <div className="section">
      <article className="integration-card">
        <div className="integration-copy">
          <p className="integration-name">Gmail</p>
          {connected && status?.google_email ? (
            <p className="muted">Connected as {status.google_email}</p>
          ) : (
            <p className="muted">
              {statusLabel(status, connecting)}
              {status && !status.configured
                ? " — Google OAuth is not configured."
                : null}
            </p>
          )}
          {connected ? (
            <p className="muted">Status: {statusLabel(status, connecting)}</p>
          ) : null}
          {status?.status === "ERROR" && status.message ? (
            <p className="notice">{status.message}</p>
          ) : null}
          {error ? <p className="notice">{error}</p> : null}
        </div>
        <div className="actions">
          {connected ? (
            <button
              className="secondary"
              type="button"
              disabled={busy}
              onClick={() => void handleDisconnect()}
            >
              Disconnect
            </button>
          ) : (
            <button
              className="primary"
              type="button"
              disabled={busy || status?.configured === false}
              onClick={() => void handleConnect()}
            >
              Connect Gmail
            </button>
          )}
        </div>
      </article>
    </div>
  );
}
