"use client";

import { KeyRound, Pencil, Plus, UserCheck, UserX } from "lucide-react";
import { useState, type FormEvent } from "react";

import { api, ApiError } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { REGION_LABELS, ROLE_LABELS, type RegionCode, type RoleName, type UserView } from "@/lib/types";

import { Pager } from "../pager";
import { Alert, Badge, Button, Card, Field, Input, inputClass, Modal, Skeleton } from "../ui";
import { usePaged } from "../use-paged";

const ROLES = Object.keys(ROLE_LABELS) as RoleName[];
const REGIONS = Object.keys(REGION_LABELS) as RegionCode[];

function RoleRegionFields({
  role,
  region,
  onRole,
  onRegion,
}: {
  role: RoleName | "";
  region: RegionCode | "";
  onRole: (role: RoleName | "") => void;
  onRegion: (region: RegionCode | "") => void;
}) {
  return (
    <div className="grid gap-4 sm:grid-cols-2">
      <Field label="Role">
        <select className={inputClass} value={role} onChange={(e) => onRole(e.target.value as RoleName | "")} aria-label="Role">
          <option value="">No role</option>
          {ROLES.map((r) => (
            <option key={r} value={r}>
              {ROLE_LABELS[r]}
            </option>
          ))}
        </select>
      </Field>
      <Field label="Region" hint={role === "sales_manager" ? "Required for sales managers" : "Only sales managers have a region"}>
        <select
          className={inputClass}
          value={region}
          disabled={role !== "sales_manager"}
          onChange={(e) => onRegion(e.target.value as RegionCode | "")}
          aria-label="Region"
        >
          <option value="">—</option>
          {REGIONS.map((r) => (
            <option key={r} value={r}>
              {REGION_LABELS[r]}
            </option>
          ))}
        </select>
      </Field>
    </div>
  );
}

function CreateUser({ onDone }: { onDone: () => void }) {
  const [form, setForm] = useState({ username: "", display_name: "", password: "" });
  const [role, setRole] = useState<RoleName | "">("");
  const [region, setRegion] = useState<RegionCode | "">("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.post("admin/users", {
        ...form,
        role: role || null,
        region: role === "sales_manager" ? region || null : null,
      });
      onDone();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not create the user.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-4">
      {error && <Alert>{error}</Alert>}
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Username" hint="Lower-case, e.g. sales.nordics">
          <Input required value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} aria-label="Username" />
        </Field>
        <Field label="Display name">
          <Input value={form.display_name} onChange={(e) => setForm({ ...form, display_name: e.target.value })} aria-label="Display name" />
        </Field>
      </div>
      <Field label="Initial password" hint="At least 10 characters. Share it with the user securely.">
        <Input required type="password" autoComplete="new-password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} aria-label="Initial password" />
      </Field>
      <RoleRegionFields role={role} region={region} onRole={(r) => { setRole(r); if (r !== "sales_manager") setRegion(""); }} onRegion={setRegion} />
      <div className="flex justify-end">
        <Button type="submit" loading={busy}>
          Create user
        </Button>
      </div>
    </form>
  );
}

function EditAccess({ user, onDone }: { user: UserView; onDone: () => void }) {
  const [role, setRole] = useState<RoleName | "">(user.role ?? "");
  const [region, setRegion] = useState<RegionCode | "">(user.region ?? "");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.patch(`admin/users/${user.id}`, { role: role || null, region: role === "sales_manager" ? region || null : null });
      onDone();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not change the role.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-4">
      {error && <Alert>{error}</Alert>}
      <p className="text-muted text-sm">The change applies to {user.username}&apos;s next request; no new login is needed.</p>
      <RoleRegionFields role={role} region={region} onRole={(r) => { setRole(r); if (r !== "sales_manager") setRegion(""); }} onRegion={setRegion} />
      <div className="flex justify-end">
        <Button type="submit" loading={busy}>
          Save access
        </Button>
      </div>
    </form>
  );
}

function ResetPassword({ user, onDone }: { user: UserView; onDone: () => void }) {
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.post(`admin/users/${user.id}/reset-password`, { new_password: password });
      onDone();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not reset the password.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-4">
      {error && <Alert>{error}</Alert>}
      <p className="text-muted text-sm">{user.username} will be signed out everywhere and must use the new password.</p>
      <Field label="New password" hint="At least 10 characters.">
        <Input required type="password" autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} aria-label="New password" />
      </Field>
      <div className="flex justify-end">
        <Button type="submit" loading={busy}>
          Reset password
        </Button>
      </div>
    </form>
  );
}

type Dialog = { kind: "create" } | { kind: "edit"; user: UserView } | { kind: "password"; user: UserView } | null;

export function UsersAdmin() {
  const [roleFilter, setRoleFilter] = useState("");
  const [activeFilter, setActiveFilter] = useState("");
  const { data, error, loading, page, setPage, pageSize, reload } = usePaged<UserView>("admin/users", {
    role: roleFilter || undefined,
    is_active: activeFilter || undefined,
  });
  const [dialog, setDialog] = useState<Dialog>(null);
  const [notice, setNotice] = useState<{ tone: "green" | "red"; text: string } | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  function done(text: string) {
    setDialog(null);
    setNotice({ tone: "green", text });
    void reload();
  }

  async function toggle(user: UserView) {
    setBusyId(user.id);
    setNotice(null);
    try {
      await api.patch(`admin/users/${user.id}`, { is_active: !user.is_active });
      setNotice({ tone: "green", text: `${user.username} is now ${user.is_active ? "disabled; existing sessions stop working at once" : "enabled"}.` });
      void reload();
    } catch (e) {
      setNotice({ tone: "red", text: e instanceof ApiError ? e.message : "Could not change the user." });
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap gap-2">
          <select className={`${inputClass} w-auto`} value={roleFilter} onChange={(e) => setRoleFilter(e.target.value)} aria-label="Filter by role">
            <option value="">All roles</option>
            {ROLES.map((r) => (
              <option key={r} value={r}>
                {ROLE_LABELS[r]}
              </option>
            ))}
          </select>
          <select className={`${inputClass} w-auto`} value={activeFilter} onChange={(e) => setActiveFilter(e.target.value)} aria-label="Filter by status">
            <option value="">Active and disabled</option>
            <option value="true">Active only</option>
            <option value="false">Disabled only</option>
          </select>
        </div>
        <Button onClick={() => setDialog({ kind: "create" })}>
          <Plus className="size-4" /> New user
        </Button>
      </div>

      {notice && <Alert tone={notice.tone}>{notice.text}</Alert>}
      {error && <Alert title="Could not load users">{error}</Alert>}

      <Card className="overflow-hidden">
        {/* Phones: one card per user with full-size actions. */}
        <ul className="divide-y divide-[var(--border)] sm:hidden" data-testid="users-cards">
          {loading && !data &&
            [0, 1, 2].map((i) => (
              <li key={i} className="p-4">
                <Skeleton className="h-16 w-full" />
              </li>
            ))}
          {data?.items.map((user) => (
            <li key={user.id} className="space-y-3 p-4">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="font-medium">{user.display_name}</p>
                  <p className="text-muted font-mono text-xs">{user.username}</p>
                </div>
                {user.is_active ? <Badge tone="green">Active</Badge> : <Badge>Disabled</Badge>}
              </div>
              <div className="flex flex-wrap items-center gap-1.5">
                {user.role ? <Badge tone={user.role === "admin" ? "amber" : "brand"}>{ROLE_LABELS[user.role]}</Badge> : <Badge tone="red">No role</Badge>}
                {user.region && <Badge>{REGION_LABELS[user.region]}</Badge>}
                <span className="text-muted text-xs">Last login {user.last_login_at ? formatDateTime(user.last_login_at) : "never"}</span>
              </div>
              <div className="grid grid-cols-3 gap-2">
                <Button variant="secondary" size="sm" className="min-h-10" onClick={() => setDialog({ kind: "edit", user })}>
                  <Pencil className="size-3.5" /> Role
                </Button>
                <Button variant="secondary" size="sm" className="min-h-10" onClick={() => setDialog({ kind: "password", user })}>
                  <KeyRound className="size-3.5" /> Password
                </Button>
                <Button variant="secondary" size="sm" className="min-h-10" loading={busyId === user.id} onClick={() => void toggle(user)}>
                  {user.is_active ? <UserX className="size-3.5" /> : <UserCheck className="size-3.5" />}
                  {user.is_active ? "Disable" : "Enable"}
                </Button>
              </div>
            </li>
          ))}
        </ul>
        <div className="hidden overflow-x-auto sm:block">
          <table className="w-full text-sm" data-testid="users-table">
            <thead className="bg-muted text-muted text-left text-xs uppercase tracking-wider">
              <tr>
                <th className="px-4 py-3 font-semibold">User</th>
                <th className="px-4 py-3 font-semibold">Role</th>
                <th className="px-4 py-3 font-semibold">Region</th>
                <th className="px-4 py-3 font-semibold">Status</th>
                <th className="px-4 py-3 font-semibold">Last login</th>
                <th className="px-4 py-3 text-right font-semibold">Actions</th>
              </tr>
            </thead>
            <tbody>
              {loading && !data &&
                [0, 1, 2, 3].map((i) => (
                  <tr key={i} className="border-t border-subtle">
                    <td colSpan={6} className="px-4 py-3">
                      <Skeleton className="h-6 w-full" />
                    </td>
                  </tr>
                ))}
              {data?.items.map((user) => (
                <tr key={user.id} className="border-t border-subtle hover:bg-muted/50">
                  <td className="px-4 py-3">
                    <p className="font-medium">{user.display_name}</p>
                    <p className="text-muted font-mono text-xs">{user.username}</p>
                  </td>
                  <td className="px-4 py-3">
                    {user.role ? <Badge tone={user.role === "admin" ? "amber" : "brand"}>{ROLE_LABELS[user.role]}</Badge> : <Badge tone="red">No role</Badge>}
                  </td>
                  <td className="px-4 py-3">{user.region ? REGION_LABELS[user.region] : <span className="text-muted">—</span>}</td>
                  <td className="px-4 py-3">{user.is_active ? <Badge tone="green">Active</Badge> : <Badge>Disabled</Badge>}</td>
                  <td className="text-muted whitespace-nowrap px-4 py-3 text-xs">{user.last_login_at ? formatDateTime(user.last_login_at) : "Never"}</td>
                  <td className="px-4 py-3">
                    <div className="flex justify-end gap-1">
                      <Button variant="ghost" size="sm" onClick={() => setDialog({ kind: "edit", user })} aria-label={`Change role of ${user.username}`}>
                        <Pencil className="size-3.5" /> <span className="hidden xl:inline">Role</span>
                      </Button>
                      <Button variant="ghost" size="sm" onClick={() => setDialog({ kind: "password", user })} aria-label={`Reset password of ${user.username}`}>
                        <KeyRound className="size-3.5" /> <span className="hidden xl:inline">Password</span>
                      </Button>
                      <Button variant="ghost" size="sm" loading={busyId === user.id} onClick={() => void toggle(user)} aria-label={`${user.is_active ? "Disable" : "Enable"} ${user.username}`}>
                        {user.is_active ? <UserX className="size-3.5" /> : <UserCheck className="size-3.5" />}
                        <span className="hidden xl:inline">{user.is_active ? "Disable" : "Enable"}</span>
                      </Button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {data && <Pager page={page} pageSize={pageSize} total={data.total} onPage={setPage} />}
      </Card>

      <Modal open={dialog?.kind === "create"} title="New user" onClose={() => setDialog(null)}>
        <CreateUser onDone={() => done("User created.")} />
      </Modal>
      {dialog?.kind === "edit" && (
        <Modal open title={`Role and region · ${dialog.user.username}`} onClose={() => setDialog(null)}>
          <EditAccess user={dialog.user} onDone={() => done(`Access for ${dialog.user.username} updated.`)} />
        </Modal>
      )}
      {dialog?.kind === "password" && (
        <Modal open title={`Reset password · ${dialog.user.username}`} onClose={() => setDialog(null)}>
          <ResetPassword user={dialog.user} onDone={() => done(`Password for ${dialog.user.username} reset.`)} />
        </Modal>
      )}
    </div>
  );
}
