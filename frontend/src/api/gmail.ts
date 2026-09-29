import { request } from "./client";

export type GmailStatus =
  | "NOT_CONNECTED"
  | "CONNECTING"
  | "CONNECTED"
  | "WATCH_ACTIVE"
  | "WATCH_EXPIRED"
  | "ERROR"
  | "DISCONNECTED";

export type GmailStatusResponse = {
  status: GmailStatus;
  google_email: string | null;
  connected_at: string | null;
  watch_expiration: string | null;
  last_email_received_at?: string | null;
  configured: boolean;
  message: string | null;
};

export function getGmailStatus() {
  return request<GmailStatusResponse>("/api/integrations/gmail/status");
}

export function startGmailConnect() {
  return request<{ authorization_url: string }>(
    "/api/integrations/gmail/connect",
  );
}

export function disconnectGmail() {
  return request<GmailStatusResponse>("/api/integrations/gmail/disconnect", {
    method: "POST",
  });
}
