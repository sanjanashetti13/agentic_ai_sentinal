import type { AgentTraceEntry, ChangeStatus } from "../types";
import {
  AGENT_ORDER,
  agentLabel,
  displayAgentSummary,
} from "../utils/format";

type AgentTraceProps = {
  entries?: AgentTraceEntry[] | null;
  changeStatus?: ChangeStatus | string | null;
};

export function AgentTrace({ entries, changeStatus }: AgentTraceProps) {
  const list = entries ?? [];
  if (list.length === 0) {
    return <p className="muted">No agent activity yet.</p>;
  }

  const invoked = new Set(list.map((item) => item.agent));

  return (
    <ol className="agent-trace">
      {AGENT_ORDER.map((agent) => {
        const entry = list.find((item) => item.agent === agent);
        const skipped =
          !invoked.has(agent) ||
          ((agent === "analysis" || agent === "action") &&
            changeStatus != null &&
            changeStatus !== "changed");
        return (
          <li
            key={agent}
            className={`agent-step ${skipped ? "skipped" : "ran"}`}
          >
            <strong>{agentLabel(agent)}</strong>
            <p>{displayAgentSummary(agent, entry, skipped, changeStatus)}</p>
            <span className="muted">{skipped ? "Skipped" : "Done"}</span>
          </li>
        );
      })}
    </ol>
  );
}
