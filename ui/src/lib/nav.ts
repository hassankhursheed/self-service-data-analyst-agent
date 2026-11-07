import type { RoleName } from "./types";

export interface NavItem {
  href: string;
  label: string;
  icon: "ask" | "history" | "monitoring" | "users" | "review" | "evaluation";
  adminOnly: boolean;
}

export const NAV: NavItem[] = [
  { href: "/", label: "Ask", icon: "ask", adminOnly: false },
  { href: "/history", label: "History", icon: "history", adminOnly: false },
  { href: "/admin/monitoring", label: "Monitoring", icon: "monitoring", adminOnly: true },
  { href: "/admin/users", label: "Users", icon: "users", adminOnly: true },
  { href: "/admin/review", label: "Review", icon: "review", adminOnly: true },
  { href: "/admin/evaluation", label: "Evaluation", icon: "evaluation", adminOnly: true },
];

/** Navigation for a role. Admins only see admin pages (they cannot ask business questions). */
export function navFor(role: RoleName | null): NavItem[] {
  if (role === "admin") return NAV.filter((item) => item.adminOnly);
  return NAV.filter((item) => !item.adminOnly);
}
