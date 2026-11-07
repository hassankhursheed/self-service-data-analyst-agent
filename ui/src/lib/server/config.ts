import "server-only";

// Server-only settings. The browser never learns the API address or the token.
export const API_BASE_URL = (process.env.API_BASE_URL ?? "http://127.0.0.1:8000").replace(/\/$/, "");
export const SESSION_COOKIE = "nw_session";
export const SESSION_MAX_AGE_SECONDS = 60 * 60; // matches auth.access_token_minutes
export const SECURE_COOKIES = process.env.NODE_ENV === "production" && process.env.UI_INSECURE_COOKIES !== "1";

// API paths the browser may reach through /api/proxy (everything else is refused).
export const PROXY_ALLOWED = [
  /^ask$/,
  /^clarify$/,
  /^feedback$/,
  /^conversations$/,
  /^conversations\/[0-9a-f-]{36}$/,
  /^conversations\/[0-9a-f-]{36}\/table$/,
  /^admin\/(users|blocked|errors|review|metrics|verified-queries|eval\/runs|eval\/run)$/,
  /^admin\/verified-queries\/[0-9a-f-]{36}$/,
  /^admin\/feedback\/\d+\/eval-case$/,
  /^admin\/users\/[0-9a-f-]{36}$/,
  /^admin\/users\/[0-9a-f-]{36}\/reset-password$/,
  /^admin\/errors\/\d+\/rerun$/,
];

export function isAllowedPath(path: string): boolean {
  return PROXY_ALLOWED.some((pattern) => pattern.test(path));
}
