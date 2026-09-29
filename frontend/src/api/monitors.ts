import { request } from "./client";
import type {
  Monitor,
  MonitorCheckResult,
  MonitorCreateInput,
  MonitorDetail,
} from "../types";

export async function getMonitors(): Promise<Monitor[]> {
  const payload = await request<{ monitors: Monitor[] }>("/api/monitors");
  return payload.monitors;
}

export function getMonitor(id: string): Promise<MonitorDetail> {
  return request<MonitorDetail>(`/api/monitors/${id}`);
}

export function createMonitor(data: MonitorCreateInput): Promise<Monitor> {
  return request<Monitor>("/api/monitors", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export function updateMonitor(
  id: string,
  data: { enabled: boolean },
): Promise<Monitor> {
  return request<Monitor>(`/api/monitors/${id}`, {
    method: "PATCH",
    body: JSON.stringify(data),
  });
}

export function checkMonitor(id: string): Promise<MonitorCheckResult> {
  return request<MonitorCheckResult>(`/api/monitors/${id}/check`, {
    method: "POST",
  });
}

export function deleteMonitor(id: string): Promise<void> {
  return request<void>(`/api/monitors/${id}`, {
    method: "DELETE",
  });
}
