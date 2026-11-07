import "server-only";

/**
 * CSRF guard for the UI's own route handlers. The session cookie is SameSite=Strict, and
 * every state-changing call must also be same-origin JSON.
 */
export function sameOriginJson(request: Request): boolean {
  if (request.method === "GET" || request.method === "HEAD") return true;
  const contentType = request.headers.get("content-type") ?? "";
  if (!contentType.toLowerCase().startsWith("application/json")) return false;
  const origin = request.headers.get("origin");
  if (!origin) return true; // same-origin fetches from older browsers may omit it
  const host = request.headers.get("x-forwarded-host") ?? request.headers.get("host");
  try {
    return new URL(origin).host === host;
  } catch {
    return false;
  }
}

export function errorJson(status: number, code: string, message: string): Response {
  return Response.json({ correlation_id: "", error: { code, message } }, { status });
}
