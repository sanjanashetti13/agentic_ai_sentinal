import { humanLoopLabel } from "../utils/format";
import { monitorStatusLabel } from "../utils/format";

type StatusBadgeProps = {
  lastChange: string | null;
  lastCheckedAt: string | null;
  checking?: boolean;
  enabled?: boolean;
  meaningful?: boolean | null;
};

export function StatusBadge({
  lastChange,
  lastCheckedAt,
  checking,
  enabled,
  meaningful,
}: StatusBadgeProps) {
  const label = monitorStatusLabel(lastChange, lastCheckedAt, {
    checking,
    enabled,
    meaningful,
  });
  const kind =
    label === "Changed"
      ? "changed"
      : label === "Waiting for scheduled check" ||
          label === "Waiting for first scheduled check" ||
          label === "Never checked"
        ? "never"
        : label === "Blocked"
          ? "blocked"
          : label === "Error"
            ? "error"
            : label === "Checking"
              ? "checking"
              : label === "Disabled"
                ? "disabled"
                : label === "Monitoring"
                  ? "monitoring"
                  : label.toLowerCase();
  return (
    <>
      <span className={`status ${kind}`}>
        <span className="status-dot" aria-hidden="true" />
        {label}
      </span>
      {meaningful && lastChange === "changed" && !checking ? (
        <span className="status changed">Meaningful change: Yes</span>
      ) : null}
    </>
  );
}

export function EnabledBadge({ enabled }: { enabled: boolean }) {
  return (
    <span className={`status ${enabled ? "enabled" : "disabled"}`}>
      {enabled ? "Enabled" : "Disabled"}
    </span>
  );
}

export function HumanLoopBadge({
  state,
}: {
  state: string | null | undefined;
}) {
  if (!state || state === "no_action") {
    return null;
  }
  const kind =
    state === "blocked_requires_user"
      ? "blocked"
      : state === "approval_required"
        ? "pending"
        : "enabled";
  return <span className={`status ${kind}`}>{humanLoopLabel(state)}</span>;
}
