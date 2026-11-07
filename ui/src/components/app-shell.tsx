"use client";

import clsx from "clsx";
import {
  Activity,
  BarChart3,
  ClipboardCheck,
  FlaskConical,
  History,
  LogOut,
  Menu,
  MessageSquareText,
  Users,
  X,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState, type ReactNode } from "react";

import { logout } from "@/lib/api";
import { navFor, type NavItem } from "@/lib/nav";
import { REGION_LABELS, ROLE_LABELS, type User } from "@/lib/types";

import { Badge } from "./ui";

const ICONS: Record<NavItem["icon"], ReactNode> = {
  ask: <MessageSquareText className="size-4" />,
  history: <History className="size-4" />,
  monitoring: <Activity className="size-4" />,
  users: <Users className="size-4" />,
  review: <ClipboardCheck className="size-4" />,
  evaluation: <FlaskConical className="size-4" />,
};

function initials(name: string): string {
  return name
    .split(/[\s.]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase())
    .join("");
}

export function IdentityBadges({ user }: { user: User }) {
  return (
    <div className="flex flex-wrap items-center gap-1.5" data-testid="identity">
      <Badge tone={user.role === "admin" ? "amber" : user.role ? "brand" : "red"}>
        {user.role ? ROLE_LABELS[user.role] : "No role assigned"}
      </Badge>
      {user.region && <Badge tone="neutral">{REGION_LABELS[user.region]}</Badge>}
      {user.role && user.role !== "admin" && !user.region && <Badge tone="neutral">All regions</Badge>}
    </div>
  );
}

function NavLinks({ user, onNavigate }: { user: User; onNavigate?: () => void }) {
  const pathname = usePathname();
  const items = navFor(user.role);
  const admin = items.some((item) => item.adminOnly);
  return (
    <nav className="space-y-1" aria-label="Main">
      {admin && <p className="text-muted px-3 pb-1 text-xs font-semibold uppercase tracking-wider">Administration</p>}
      {items.map((item) => {
        const active = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
        return (
          <Link
            key={item.href}
            href={item.href}
            onClick={onNavigate}
            aria-current={active ? "page" : undefined}
            className={clsx(
              "flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors",
              active
                ? "bg-brand-50 text-brand-700 dark:bg-brand-900/40 dark:text-brand-200"
                : "text-muted hover:bg-muted hover:text-[var(--text)]",
            )}
          >
            {ICONS[item.icon]}
            {item.label}
          </Link>
        );
      })}
    </nav>
  );
}

function Brand() {
  return (
    <Link href="/" className="flex items-center gap-2.5 px-3">
      <div className="rounded-lg bg-brand-600 p-1.5 text-white shadow-sm">
        <BarChart3 className="size-4" />
      </div>
      <span className="font-semibold tracking-tight">Northwind Analyst</span>
    </Link>
  );
}

export function AppShell({ user, children }: { user: User; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const name = user.display_name || user.username;
  return (
    <div className="min-h-dvh lg:grid lg:grid-cols-[16rem_1fr]">
      {/* Sidebar (desktop) */}
      <aside className="surface sticky top-0 hidden h-dvh flex-col gap-6 border-y-0 border-l-0 py-5 lg:flex">
        <Brand />
        <div className="flex-1 px-3">
          <NavLinks user={user} />
        </div>
        <p className="text-muted px-6 text-xs">Fictional Northwind data · read-only</p>
      </aside>

      {/* Drawer (mobile) */}
      {open && (
        <div className="fixed inset-0 z-40 lg:hidden" role="dialog" aria-modal="true" aria-label="Menu">
          <button className="absolute inset-0 bg-slate-950/50" aria-label="Close menu" onClick={() => setOpen(false)} />
          <aside className="surface absolute inset-y-0 left-0 flex w-72 flex-col gap-6 py-5 shadow-xl animate-fade-up">
            <div className="flex items-center justify-between pr-3">
              <Brand />
              <button onClick={() => setOpen(false)} className="text-muted rounded-md p-1.5 hover:bg-muted" aria-label="Close menu">
                <X className="size-5" />
              </button>
            </div>
            <div className="px-3">
              <NavLinks user={user} onNavigate={() => setOpen(false)} />
            </div>
          </aside>
        </div>
      )}

      <div className="flex min-w-0 flex-col">
        <header className="surface sticky top-0 z-30 flex items-center gap-3 border-x-0 border-t-0 px-4 py-3 backdrop-blur sm:px-6">
          <button
            className="text-muted -ml-1 rounded-md p-1.5 hover:bg-muted lg:hidden"
            onClick={() => setOpen(true)}
            aria-label="Open menu"
          >
            <Menu className="size-5" />
          </button>
          <div className="flex-1" />
          <div className="flex min-w-0 items-center gap-3">
            <div className="hidden min-w-0 text-right sm:block">
              <p className="truncate text-sm font-semibold" data-testid="user-name">
                {name}
              </p>
              <div className="flex justify-end">
                <IdentityBadges user={user} />
              </div>
            </div>
            <div
              className="flex size-9 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-brand-500 to-indigo-400 text-sm font-semibold text-white"
              title={`${name} (${user.username})`}
              aria-hidden
            >
              {initials(name)}
            </div>
            <button
              onClick={() => void logout()}
              className="text-muted inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-sm hover:bg-muted hover:text-[var(--text)]"
            >
              <LogOut className="size-4" />
              <span className="hidden sm:inline">Log out</span>
            </button>
          </div>
        </header>
        {/* Identity is always visible, also on small screens. */}
        <div className="surface flex items-center justify-between gap-2 border-x-0 border-t-0 px-4 py-2 sm:hidden">
          <span className="truncate text-sm font-medium">{name}</span>
          <IdentityBadges user={user} />
        </div>
        <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-6 sm:px-6 lg:py-8">{children}</main>
      </div>
    </div>
  );
}

export function PageHeader({ title, description, actions }: { title: string; description?: string; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        {description && <p className="text-muted mt-1 text-sm">{description}</p>}
      </div>
      {actions}
    </div>
  );
}
