import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("server-only", () => ({}));

const jar = new Map<string, string>();
const setCookie = vi.fn((name: string, value: string, options: Record<string, unknown>) => {
  jar.set(name, value);
  return options;
});
vi.mock("next/headers", () => ({
  cookies: async () => ({
    get: (name: string) => (jar.has(name) ? { name, value: jar.get(name)! } : undefined),
    set: setCookie,
    delete: (name: string) => jar.delete(name),
  }),
}));

const { isAllowedPath } = await import("./config");
const proxy = await import("@/app/api/proxy/[...path]/route");
const session = await import("@/app/api/session/route");

const ctx = (path: string) => ({ params: Promise.resolve({ path: path.split("/") }) });
const json = (body: unknown, init: ResponseInit = {}) =>
  new Response(JSON.stringify(body), { headers: { "Content-Type": "application/json" }, ...init });

beforeEach(() => {
  jar.clear();
  setCookie.mockClear();
});

describe("proxy allow-list", () => {
  it("allows only the API paths the UI uses", () => {
    expect(isAllowedPath("ask")).toBe(true);
    expect(isAllowedPath("admin/errors/12/rerun")).toBe(true);
    expect(isAllowedPath("conversations/0b7d4c1a-6a8e-4c43-9f0f-2a1e5b8c9d10/table")).toBe(true);
    for (const path of ["auth/login", "health", "docs", "openapi.json", "admin/users/../../x", "ask/../admin"]) {
      expect(isAllowedPath(path)).toBe(false);
    }
  });
});

describe("/api/proxy", () => {
  it("adds the token from the httpOnly cookie and never returns it", async () => {
    jar.set("nw_session", "secret-token");
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(json({ status: "ANSWERED" }, { headers: { "Content-Type": "application/json", "X-Correlation-ID": "abc" } }));
    const request = new Request("http://ui.test/api/proxy/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json", Origin: "http://ui.test", Host: "ui.test" },
      body: JSON.stringify({ question: "Revenue?" }),
    });
    const response = await proxy.POST(request, ctx("ask"));
    expect(response.status).toBe(200);
    const [url, init] = fetchSpy.mock.calls[0]!;
    expect(String(url)).toMatch(/\/ask$/);
    expect(new Headers(init?.headers).get("Authorization")).toBe("Bearer secret-token");
    expect(response.headers.get("X-Correlation-ID")).toBe("abc");
    expect(await response.text()).not.toContain("secret-token");
  });

  it("refuses unknown paths, missing sessions and cross-site posts", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    expect((await proxy.GET(new Request("http://ui.test/api/proxy/docs"), ctx("docs"))).status).toBe(404);
    expect((await proxy.GET(new Request("http://ui.test/api/proxy/conversations"), ctx("conversations"))).status).toBe(401);
    jar.set("nw_session", "secret-token");
    const crossSite = new Request("http://ui.test/api/proxy/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json", Origin: "https://evil.example", Host: "ui.test" },
      body: "{}",
    });
    expect((await proxy.POST(crossSite, ctx("ask"))).status).toBe(403);
    const form = new Request("http://ui.test/api/proxy/ask", {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded", Host: "ui.test" },
      body: "question=x",
    });
    expect((await proxy.POST(form, ctx("ask"))).status).toBe(403);
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("forgets the session when the API says the token is no longer valid", async () => {
    jar.set("nw_session", "old-token");
    vi.spyOn(globalThis, "fetch").mockResolvedValue(json({ error: { code: "INVALID_TOKEN" } }, { status: 401 }));
    const response = await proxy.GET(new Request("http://ui.test/api/proxy/conversations"), ctx("conversations"));
    expect(response.status).toBe(401);
    expect(jar.has("nw_session")).toBe(false);
  });
});

describe("/api/session", () => {
  it("stores the token in an httpOnly SameSite=Strict cookie and returns only the user", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      json({ correlation_id: "c", access_token: "jwt-value", token_type: "bearer", expires_in: 3600, user: { username: "sales.europe" } }),
    );
    const response = await session.POST(
      new Request("http://ui.test/api/session", {
        method: "POST",
        headers: { "Content-Type": "application/json", Host: "ui.test" },
        body: JSON.stringify({ username: "sales.europe", password: "x" }),
      }),
    );
    const body = await response.json();
    expect(body.user.username).toBe("sales.europe");
    expect(JSON.stringify(body)).not.toContain("jwt-value");
    expect(setCookie).toHaveBeenCalledWith(
      "nw_session",
      "jwt-value",
      expect.objectContaining({ httpOnly: true, sameSite: "strict", path: "/" }),
    );
  });

  it("passes login errors through without setting a cookie", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      json({ correlation_id: "c", error: { code: "INVALID_CREDENTIALS", message: "The username or password is not correct." } }, { status: 401 }),
    );
    const response = await session.POST(
      new Request("http://ui.test/api/session", {
        method: "POST",
        headers: { "Content-Type": "application/json", Host: "ui.test" },
        body: "{}",
      }),
    );
    expect(response.status).toBe(401);
    expect(setCookie).not.toHaveBeenCalled();
  });
});
