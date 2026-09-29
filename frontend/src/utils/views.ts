export type AppView =
  | "dashboard"
  | "monitors"
  | "gmail"
  | "alerts"
  | "integrations";

export const VIEW_PATHS: Record<AppView, string> = {
  dashboard: "/",
  monitors: "/monitors",
  gmail: "/gmail",
  alerts: "/alerts",
  integrations: "/integrations",
};

export function viewFromPath(pathname: string): AppView {
  if (pathname.startsWith("/gmail")) {
    return "gmail";
  }
  if (pathname.startsWith("/monitors")) {
    return "monitors";
  }
  if (pathname.startsWith("/alerts")) {
    return "alerts";
  }
  if (pathname.startsWith("/integrations")) {
    return "integrations";
  }
  return "dashboard";
}

export function isWebsiteMonitor(monitor: { kind?: string | null }): boolean {
  return (monitor.kind ?? "website") !== "gmail";
}

export function isGmailMonitor(monitor: { kind?: string | null }): boolean {
  return monitor.kind === "gmail";
}
