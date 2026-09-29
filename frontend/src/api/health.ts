import { request } from "./client";
import type { SystemStatus } from "../types";

export type HealthResponse = {
  status: string;
  service: string;
};

export function getHealth(): Promise<HealthResponse> {
  return request<HealthResponse>("/health");
}

export function getSystemStatus(): Promise<SystemStatus> {
  return request<SystemStatus>("/api/status");
}
