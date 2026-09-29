import { useEffect, useRef, useState } from "react";
import type { Alert, Observation } from "../types";
import { formatLogTime } from "../utils/format";

type LogTone = "quiet" | "changed" | "error";

type LogEntry = {
  id: string;
  checkedAt: string;
  event: string;
  message: string;
  tone: LogTone;
  details?: string[];
};

function resultEvent(status: Observation["change_status"]): string {
  if (status === "baseline") {
    return "INITIALIZED";
  }
  if (status === "unchanged") {
    return "UNCHANGED";
  }
  if (status === "changed") {
    return "CHANGED";
  }
  if (status === "blocked") {
    return "ERROR";
  }
  if (status === "error") {
    return "ERROR";
  }
  return "CHECK";
}

function observationEntries(
  observation: Observation,
  alert: Alert | undefined,
): LogEntry[] {
  const checkedAt = observation.checked_at;
  const failed =
    observation.change_status === "error" ||
    observation.change_status === "blocked";
  const result = resultEvent(observation.change_status);
  const tone: LogTone =
    result === "CHANGED" ? "changed" : result === "ERROR" ? "error" : "quiet";
  const entries: LogEntry[] = [
    {
      id: `${observation.id}-start`,
      checkedAt,
      event: "CHECK_STARTED",
      message: "Check started.",
      tone: "quiet",
    },
  ];
  if (failed) {
    entries.push({
      id: `${observation.id}-error`,
      checkedAt,
      event: "ERROR",
      message: observation.summary || "The source could not be fetched.",
      tone: "error",
      details: observation.content_hash
        ? [`Content hash: ${observation.content_hash}`]
        : undefined,
    });
    return entries;
  }
  entries.push({
    id: `${observation.id}-fetch`,
    checkedAt,
    event: "FETCH_SUCCESS",
    message: observation.content_hash
      ? `Content hash: ${observation.content_hash}`
      : "Fetched the source.",
    tone: "quiet",
  });
  entries.push({
    id: `${observation.id}-result`,
    checkedAt,
    event: `RESULT: ${result}`,
    message:
      observation.summary ||
      (result === "UNCHANGED"
        ? "No meaningful changes detected."
        : result === "INITIALIZED"
          ? "Baseline recorded."
          : "Check completed."),
    tone,
    details: [
      observation.reason,
      observation.relevant_excerpt
        ? `Evidence: ${observation.relevant_excerpt}`
        : null,
    ].filter((item): item is string => Boolean(item)),
  });
  if (result === "CHANGED" && alert) {
    entries.push({
      id: `${observation.id}-alert`,
      checkedAt,
      event: "ALERT_GENERATED",
      message: alert.summary || observation.summary,
      tone: "changed",
    });
  }
  return entries;
}

function LogRow({ entry }: { entry: LogEntry }) {
  const [open, setOpen] = useState(entry.tone !== "quiet");
  const hasDetails = Boolean(entry.details && entry.details.length > 0);
  return (
    <article className={`monitor-log ${entry.tone}`}>
      <button
        className="monitor-log-line"
        type="button"
        onClick={() => hasDetails && setOpen((value) => !value)}
        disabled={!hasDetails}
      >
        <time dateTime={entry.checkedAt}>{formatLogTime(entry.checkedAt)}</time>
        <span className={`monitor-log-event ${entry.tone}`}>{entry.event}</span>
        <span className="monitor-log-message">{entry.message}</span>
      </button>
      {hasDetails && open ? (
        <div className="monitor-log-details">
          {entry.details?.map((item) => (
            <p key={item}>{item}</p>
          ))}
        </div>
      ) : null}
    </article>
  );
}

export function MonitorLogs({
  observations,
  alerts,
}: {
  observations: Observation[];
  alerts: Alert[];
}) {
  const chronological = [...observations].sort((a, b) =>
    a.checked_at < b.checked_at ? -1 : 1,
  );
  const entries = chronological.flatMap((observation) =>
    observationEntries(
      observation,
      alerts.find(
        (item) =>
          item.monitor_id === observation.monitor_id &&
          item.content_hash === observation.content_hash,
      ),
    ),
  );
  const logRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const node = logRef.current;
    if (node) {
      node.scrollTop = node.scrollHeight;
    }
  }, [entries.length]);

  if (entries.length === 0) {
    return (
      <p className="empty log-empty">
        No checks yet. Logs appear here after the first scheduled check.
      </p>
    );
  }

  return (
    <div className="monitor-logs" role="log" aria-label="Monitor logs" ref={logRef}>
      {entries.map((entry) => (
        <LogRow key={entry.id} entry={entry} />
      ))}
    </div>
  );
}
