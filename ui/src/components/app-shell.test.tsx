import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { navFor } from "@/lib/nav";
import { adminUser, salesUser } from "@/test/fixtures";

import { AppShell } from "./app-shell";

vi.mock("next/navigation", () => ({ usePathname: () => "/" }));

describe("navigation by role", () => {
  it("never offers admin pages to non-admins", () => {
    for (const role of ["sales_manager", "finance_analyst", "operations_manager", null] as const) {
      expect(navFor(role).some((item) => item.href.startsWith("/admin"))).toBe(false);
    }
    expect(navFor("admin").every((item) => item.href.startsWith("/admin"))).toBe(true);
  });

  it("shows the logged-in user, role and region, and no admin links for a sales manager", () => {
    render(<AppShell user={salesUser}>content</AppShell>);
    expect(screen.getAllByText("Europe Sales").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Sales manager").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Europe").length).toBeGreaterThan(0);
    expect(screen.queryByRole("link", { name: /users/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /monitoring/i })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: /history/i })).toBeInTheDocument();
  });

  it("shows the admin pages to an admin", () => {
    render(<AppShell user={adminUser}>content</AppShell>);
    for (const name of [/monitoring/i, /users/i, /review/i, /evaluation/i]) {
      expect(screen.getByRole("link", { name })).toBeInTheDocument();
    }
    expect(screen.getAllByText("Administrator").length).toBeGreaterThan(0);
  });
});
