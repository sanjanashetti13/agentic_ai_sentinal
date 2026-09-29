export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, "") ||
  "http://localhost:8000";

function detailMessage(detail: unknown): string {
  if (typeof detail === "string") {
    return detail;
  }
  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        if (item && typeof item === "object" && "msg" in item) {
          return String(item.msg);
        }
        return JSON.stringify(item);
      })
      .join(" ");
  }
  if (detail && typeof detail === "object" && "message" in detail) {
    const message = (detail as { message?: unknown }).message;
    if (typeof message === "string" && message.trim()) {
      return message;
    }
  }
  return "The request failed.";
}

export async function request<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...options,
      credentials: "include",
      headers: {
        "Content-Type": "application/json",
        ...(options.headers ?? {}),
      },
    });
  } catch {
    throw new ApiError(
      "Could not reach the Sentinel API. Confirm the backend is running.",
      0,
    );
  }

  if (!response.ok) {
    let detail: unknown = null;
    try {
      const body = (await response.json()) as { detail?: unknown };
      detail = body.detail;
    } catch {
      detail = null;
    }
    const fallback =
      response.status === 404
        ? "The requested item was not found."
        : response.status >= 500
          ? "The Sentinel API could not complete this check."
          : "The request failed.";
    const message = detailMessage(detail);
    throw new ApiError(
      message === "The request failed." ? fallback : message,
      response.status,
    );
  }

  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

export function apiBaseUrl(): string {
  return API_BASE_URL;
}
