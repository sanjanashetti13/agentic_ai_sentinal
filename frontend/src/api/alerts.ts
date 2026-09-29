import { request } from "./client";
import type { Alert, AlertStatus } from "../types";

export async function getAlerts(status?: AlertStatus): Promise<Alert[]> {
  const query = status ? `?status=${status}` : "";
  const payload = await request<{ alerts: Alert[] }>(`/api/alerts${query}`);
  return payload.alerts;
}

export function getAlert(id: string): Promise<Alert> {
  return request<Alert>(`/api/alerts/${id}`);
}

export function updateAlertStatus(
  id: string,
  status: AlertStatus,
): Promise<Alert> {
  return request<Alert>(`/api/alerts/${id}`, {
    method: "PATCH",
    body: JSON.stringify({ status }),
  });
}
