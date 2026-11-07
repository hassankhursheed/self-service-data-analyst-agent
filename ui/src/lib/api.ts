// Browser-side API client: every call goes through the UI's own /api routes.

import type { ApiErrorBody } from "./types";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly correlationId: string,
  ) {
    super(message);
  }
}

const FRIENDLY: Record<string, string> = {
  RATE_LIMITED: "You are sending requests quickly. Please wait a moment and try again.",
  SERVICE_UNAVAILABLE: "The analytics service is not reachable. Please try again shortly.",
};

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api/proxy/${path}`, {
      method,
      headers: body === undefined ? undefined : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
      credentials: "same-origin",
    });
  } catch {
    throw new ApiError(0, "NETWORK", "Could not reach the server. Check your connection.", "");
  }
  const data = (await response.json().catch(() => null)) as unknown;
  if (!response.ok) {
    const error = (data as ApiErrorBody | null)?.error;
    const code = error?.code ?? "HTTP_ERROR";
    if (response.status === 401 && typeof window !== "undefined") {
      // A full page load on purpose: it drops all client state of the old session.
      // eslint-disable-next-line @next/next/no-location-assign-relative-destination
      window.location.href = "/login?expired=1";
    }
    throw new ApiError(
      response.status,
      code,
      FRIENDLY[code] ?? error?.message ?? "Something went wrong. Please try again.",
      (data as ApiErrorBody | null)?.correlation_id ?? response.headers.get("x-correlation-id") ?? "",
    );
  }
  return data as T;
}

export const api = {
  get: <T>(path: string) => request<T>("GET", path),
  post: <T>(path: string, body: unknown = {}) => request<T>("POST", path, body),
  patch: <T>(path: string, body: unknown) => request<T>("PATCH", path, body),
};

export async function logout(): Promise<void> {
  await fetch("/api/session", { method: "DELETE", headers: { "Content-Type": "application/json" } });
  // eslint-disable-next-line @next/next/no-location-assign-relative-destination
  window.location.href = "/login"; // full load: nothing of the session stays in memory
}
