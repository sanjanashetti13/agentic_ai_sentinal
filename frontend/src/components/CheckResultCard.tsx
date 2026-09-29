import type { MonitorCheckResult } from "../types";
import { actionTypeLabel, oneLine, yesNo } from "../utils/format";
import { HumanLoopNotice } from "./HumanLoopNotice";
import { StatusBadge } from "./StatusBadge";

export function CheckResultCard({
  result,
  onOpenAlert,
}: {
  result: MonitorCheckResult;
  onOpenAlert?: () => void;
}) {
  return (
    <div className="check-result">
      <StatusBadge
        lastChange={result.change_status}
        lastCheckedAt={result.checked_at}
        meaningful={result.meaningful_change}
      />
      {" · "}
      Meaningful: {yesNo(result.meaningful_change)}
      {" · "}
      Action: {actionTypeLabel(result.action_type)}
      {result.alert_id ? " · Alert created" : ""}
      {result.fetch_method ? ` · Fetch: ${result.fetch_method}` : ""}
      <p className="muted">{result.message ?? result.summary}</p>
      {result.observed_facts && result.observed_facts.length > 0 ? (
        <ul className="observed-facts">
          {result.observed_facts.map((fact) => (
            <li key={fact}>{fact}</li>
          ))}
        </ul>
      ) : null}
      {result.previous_observation || result.current_observation ? (
        <p className="muted">
          {result.previous_observation
            ? `Previous: ${oneLine(result.previous_observation)}`
            : ""}
          {result.previous_observation && result.current_observation
            ? " · "
            : ""}
          {result.current_observation
            ? `Current: ${oneLine(result.current_observation)}`
            : ""}
        </p>
      ) : null}
      {result.alert_id && onOpenAlert ? (
        <button className="secondary" type="button" onClick={onOpenAlert}>
          View alert
        </button>
      ) : null}
      <HumanLoopNotice state={result.human_loop_state} />
    </div>
  );
}
