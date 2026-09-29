import type { AgentTraceEntry, ChangeStatus } from "../types";

export const AGENT_ORDER = [
  "supervisor",
  "monitoring",
  "analysis",
  "action",
] as const;

export type AgentName = (typeof AGENT_ORDER)[number];

export function formatDateTime(value: string | null | undefined): string {
  if (!value) {
    return "Never";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "Unknown";
  }
  return date.toLocaleString();
}

export function formatLogTime(value: string | null | undefined): string {
  if (!value) {
    return "";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "Unknown";
  }
  return date.toLocaleTimeString();
}

export function formatRelativeTime(value: string | null | undefined): string {
  if (!value) {
    return "Never";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "Unknown";
  }
  const seconds = Math.max(
    0,
    Math.round((Date.now() - date.getTime()) / 1000),
  );
  if (seconds < 8) {
    return "just now";
  }
  if (seconds < 60) {
    return `${seconds} seconds ago`;
  }
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) {
    return `${minutes} minute${minutes === 1 ? "" : "s"} ago`;
  }
  const hours = Math.round(minutes / 60);
  if (hours < 48) {
    return `${hours} hour${hours === 1 ? "" : "s"} ago`;
  }
  return formatDateTime(value);
}

export function formatLastChecked(value: string | null | undefined): string {
  if (!value) {
    return "Waiting for scheduled check";
  }
  return formatRelativeTime(value);
}

export function oneLine(value: string | null | undefined): string {
  return (value ?? "").replace(/\s+/g, " ").trim();
}

export function monitorStatusLabel(
  lastChange: string | null,
  lastCheckedAt: string | null,
  options?: {
    enabled?: boolean;
    checking?: boolean;
    meaningful?: boolean | null;
  },
): string {
  if (options?.checking) {
    return "Checking";
  }
  if (options?.enabled === false) {
    return "Disabled";
  }
  if (!lastCheckedAt) {
    return "Waiting for scheduled check";
  }
  if (lastChange === "blocked") {
    return "Blocked";
  }
  if (lastChange === "error") {
    return "Error";
  }
  if (lastChange === "baseline") {
    return "Baseline";
  }
  if (lastChange === "unchanged") {
    return "Unchanged";
  }
  if (lastChange === "changed") {
    return "Changed";
  }
  return "Monitoring";
}

export function checkStatusLabel(status: string | null | undefined): string {
  if (status === "baseline") {
    return "Baseline";
  }
  if (status === "unchanged") {
    return "Unchanged";
  }
  if (status === "changed") {
    return "Changed";
  }
  if (status === "blocked") {
    return "Blocked";
  }
  if (status === "error") {
    return "Error";
  }
  return "Checked";
}

export function humanLoopLabel(state: string | null | undefined): string {
  if (state === "blocked_requires_user") {
    return "Blocked";
  }
  if (state === "approval_required") {
    return "Approval required";
  }
  if (state === "notification") {
    return "Notification";
  }
  if (state === "no_action") {
    return "No action";
  }
  return "";
}

export function humanLoopDescription(state: string | null | undefined): string {
  if (state === "notification") {
    return "Sentinel can notify you.";
  }
  if (state === "approval_required") {
    return "User approval required before taking this action.";
  }
  if (state === "blocked_requires_user") {
    return "User intervention required because authentication/CAPTCHA/OTP is needed. Sentinel does not bypass security.";
  }
  if (state === "no_action") {
    return "No follow-up action.";
  }
  return "";
}

export function agentLabel(agent: string): string {
  if (agent === "supervisor") {
    return "Supervisor Agent";
  }
  if (agent === "monitoring") {
    return "Monitoring Agent";
  }
  if (agent === "analysis") {
    return "Analysis Agent";
  }
  if (agent === "action") {
    return "Action Agent";
  }
  return agent;
}

export function agentDefaultRole(agent: string): string {
  if (agent === "supervisor") {
    return "Coordinator";
  }
  if (agent === "monitoring") {
    return "Source observation";
  }
  if (agent === "analysis") {
    return "Goal-aware relevance";
  }
  if (agent === "action") {
    return "Action decision";
  }
  return "";
}

export function actionTypeLabel(action: string | null | undefined): string {
  if (!action) {
    return "—";
  }
  if (action === "notify_user") {
    return "Notify user";
  }
  if (action === "create_alert") {
    return "Create alert";
  }
  if (action === "request_approval") {
    return "Request approval";
  }
  if (action === "ignore") {
    return "Ignore";
  }
  return action;
}

export function yesNo(value: boolean | null | undefined): string {
  if (value == null) {
    return "—";
  }
  return value ? "Yes" : "No";
}

export function validateMonitorInput(
  goal: string,
  url: string,
): string | null {
  if (!goal.trim()) {
    return "A monitoring goal is required.";
  }
  const trimmedUrl = url.trim();
  if (!trimmedUrl) {
    return "A webpage URL is required.";
  }
  let parsed: URL;
  try {
    parsed = new URL(trimmedUrl);
  } catch {
    return "Enter a valid URL, for example http://127.0.0.1:8765/";
  }
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
    return "URL must start with http:// or https://.";
  }
  if (!parsed.hostname) {
    return "URL is missing a hostname.";
  }
  return null;
}

export function actionFromTrace(
  entries: AgentTraceEntry[] | null | undefined,
): string | null {
  const action = entries?.find((item) => item.agent === "action");
  return action?.summary ?? null;
}

export function displayAgentSummary(
  agent: AgentName,
  entry: AgentTraceEntry | undefined,
  skipped: boolean,
  changeStatus: ChangeStatus | string | null | undefined,
): string {
  if (skipped || !entry) {
    if (agent === "analysis" || agent === "action") {
      if (changeStatus === "baseline" || changeStatus === "unchanged") {
        return `Skipped because this check is ${changeStatus}.`;
      }
      if (changeStatus === "blocked") {
        return "Skipped because the source is blocked.";
      }
      if (changeStatus === "error") {
        return "Skipped because the source could not be fetched.";
      }
      return "Not invoked for this check.";
    }
    return "Not invoked.";
  }
  if (agent === "action") {
    const known = ["ignore", "create_alert", "notify_user", "request_approval"];
    if (known.includes(entry.summary)) {
      return `Selected ${entry.summary}`;
    }
  }
  return entry.summary;
}

export const DEMO_GOAL =
  "Tell me if the application submission deadline changes.";
export const DEMO_URL = "http://127.0.0.1:8765/";
