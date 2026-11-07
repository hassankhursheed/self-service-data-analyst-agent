import { NextResponse, type NextRequest } from "next/server";

// Pages need a session cookie; without one the user goes to the login screen. The cookie
// itself is checked by the API on every call (and by the layout through /auth/me).
export function proxy(request: NextRequest): NextResponse {
  const hasSession = request.cookies.has("nw_session");
  const { pathname } = request.nextUrl;
  if (!hasSession && pathname !== "/login") {
    return NextResponse.redirect(new URL("/login", request.url));
  }
  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!api/|_next/|favicon\\.ico|icon\\.svg|login).*)"],
};
