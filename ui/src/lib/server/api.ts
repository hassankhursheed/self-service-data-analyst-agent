import "server-only";

import { cookies } from "next/headers";

import type { User } from "@/lib/types";

import { API_BASE_URL, SESSION_COOKIE } from "./config";

/** Call the FastAPI service from the server, with the session token if there is one. */
export async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const token = (await cookies()).get(SESSION_COOKIE)?.value;
  const headers = new Headers(init.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  return fetch(`${API_BASE_URL}/${path.replace(/^\//, "")}`, { ...init, headers, cache: "no-store" });
}

/** The logged-in user with their current role and region, or null when not logged in. */
export async function getCurrentUser(): Promise<User | null> {
  const token = (await cookies()).get(SESSION_COOKIE)?.value;
  if (!token) return null;
  try {
    const response = await apiFetch("auth/me");
    if (!response.ok) return null;
    const body = (await response.json()) as { user: User };
    return body.user;
  } catch {
    return null;
  }
}
