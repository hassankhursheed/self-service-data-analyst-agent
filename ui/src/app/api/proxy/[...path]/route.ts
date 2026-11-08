import { cookies } from "next/headers";

import { isAllowedPath, SESSION_COOKIE } from "@/lib/server/config";
import { apiFetch } from "@/lib/server/api";
import { errorJson, sameOriginJson } from "@/lib/server/guard";

type Context = { params: Promise<{ path: string[] }> };

/**
 * Forward a browser call to the FastAPI service with the token from the httpOnly cookie.
 * Only listed API paths are reachable; the token is never sent back to the browser.
 */
async function forward(request: Request, context: Context): Promise<Response> {
  const { path } = await context.params;
  const target = path.join("/");
  if (!isAllowedPath(target)) return errorJson(404, "NOT_FOUND", "Not found.");
  if (!sameOriginJson(request)) return errorJson(403, "FORBIDDEN", "Request refused.");
  const store = await cookies();
  if (!store.get(SESSION_COOKIE)) {
    return errorJson(401, "INVALID_TOKEN", "Please log in to continue.");
  }

  const search = new URL(request.url).search;
  const headers = new Headers({ Accept: "application/json" });
  const correlationId = request.headers.get("x-correlation-id");
  if (correlationId) headers.set("X-Correlation-ID", correlationId);
  const hasBody = request.method !== "GET" && request.method !== "HEAD";
  if (hasBody) headers.set("Content-Type", "application/json");

  let response: Response;
  try {
    response = await apiFetch(`${target}${search}`, {
      method: request.method,
      headers,
      body: hasBody ? await request.text() : undefined,
    });
  } catch {
    return errorJson(503, "SERVICE_UNAVAILABLE", "The analytics service is not reachable. Please try again shortly.");
  }
  if (response.status === 401) store.delete(SESSION_COOKIE);
  const out = new Headers({ "Content-Type": response.headers.get("content-type") ?? "application/json" });
  const id = response.headers.get("x-correlation-id");
  if (id) out.set("X-Correlation-ID", id);
  const disposition = response.headers.get("content-disposition");
  if (disposition) out.set("Content-Disposition", disposition); // CSV downloads
  return new Response(response.body, { status: response.status, headers: out });
}

export const GET = forward;
export const POST = forward;
export const PATCH = forward;
