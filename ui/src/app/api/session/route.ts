import { cookies } from "next/headers";

import { API_BASE_URL, SECURE_COOKIES, SESSION_COOKIE, SESSION_MAX_AGE_SECONDS } from "@/lib/server/config";
import { errorJson, sameOriginJson } from "@/lib/server/guard";

/** Log in: the API's token goes into an httpOnly cookie; the browser gets only the user. */
export async function POST(request: Request): Promise<Response> {
  if (!sameOriginJson(request)) return errorJson(403, "FORBIDDEN", "Request refused.");
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: await request.text(),
      cache: "no-store",
    });
  } catch {
    return errorJson(503, "SERVICE_UNAVAILABLE", "The analytics service is not reachable. Please try again shortly.");
  }
  const body = await response.json();
  if (!response.ok) return Response.json(body, { status: response.status });
  (await cookies()).set(SESSION_COOKIE, body.access_token, {
    httpOnly: true,
    sameSite: "strict",
    secure: SECURE_COOKIES,
    path: "/",
    maxAge: Math.min(body.expires_in ?? SESSION_MAX_AGE_SECONDS, SESSION_MAX_AGE_SECONDS),
  });
  return Response.json({ correlation_id: body.correlation_id, user: body.user });
}

/** Log out: forget the token. */
export async function DELETE(request: Request): Promise<Response> {
  if (!sameOriginJson(request)) return errorJson(403, "FORBIDDEN", "Request refused.");
  (await cookies()).delete(SESSION_COOKIE);
  return new Response(null, { status: 204 });
}
