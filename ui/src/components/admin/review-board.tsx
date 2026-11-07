"use client";

import { BadgeCheck, BookCheck, FlaskConical, Pencil, RotateCw, ShieldAlert, ThumbsDown, TriangleAlert } from "lucide-react";
import { useState, type FormEvent, type ReactNode } from "react";

import { api, ApiError } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { BUSINESS_ROLES, ROLE_LABELS, type ReviewItem, type ReviewKind, type RoleName, type VerifiedQuery } from "@/lib/types";

import { Pager } from "../pager";
import { Alert, Badge, Button, Card, EmptyState, Field, Input, inputClass, Modal, Skeleton, type Tone } from "../ui";
import { usePaged } from "../use-paged";

const KIND: Record<ReviewKind, { label: string; tone: Tone; icon: ReactNode }> = {
  not_helpful: { label: "Not helpful", tone: "amber", icon: <ThumbsDown className="size-3" /> },
  blocked: { label: "Blocked", tone: "red", icon: <ShieldAlert className="size-3" /> },
  failure: { label: "Failure", tone: "red", icon: <TriangleAlert className="size-3" /> },
};

const CASE_TYPES = ["simple", "medium", "hard", "ambiguous", "unsafe", "access_control"] as const;
const BEHAVIOURS = ["correct_result", "clarify", "blocked", "rejected", "region_only", "empty_result"] as const;

type Notice = { tone: "green" | "red"; text: string } | null;

function isRole(value: string | null): value is RoleName {
  return value !== null && (BUSINESS_ROLES as string[]).includes(value);
}

// --- dialogs ---------------------------------------------------------------------------

interface VerifyDraft {
  question_text: string;
  sql_text: string;
  description: string;
  allowed_roles: RoleName[];
  metrics_used: string[];
  source_question_id: string | null;
  lineage_id: string | null;
}

/** Save a question and its SQL as verified, or correct an example (new version). */
export function VerifyForm({ draft, onDone }: { draft: VerifyDraft; onDone: (text: string) => void }) {
  const [form, setForm] = useState(draft);
  const [metrics, setMetrics] = useState(draft.metrics_used.join(", "));
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  function toggleRole(role: RoleName) {
    setForm((f) => ({
      ...f,
      allowed_roles: f.allowed_roles.includes(role) ? f.allowed_roles.filter((r) => r !== role) : [...f.allowed_roles, role],
    }));
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const saved = await api.post<VerifiedQuery>("admin/verified-queries", {
        ...form,
        metrics_used: metrics
          .split(",")
          .map((m) => m.trim())
          .filter(Boolean),
      });
      onDone(draft.lineage_id ? `Saved version ${saved.version} of the example.` : "Saved to the verified library.");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not save.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-4">
      {error && <Alert title="Not saved">{error}</Alert>}
      <p className="text-muted text-sm">The SQL is checked by the same validator as agent SQL, for every role you allow.</p>
      <Field label="Question">
        <Input required value={form.question_text} onChange={(e) => setForm({ ...form, question_text: e.target.value })} aria-label="Question" />
      </Field>
      <Field label="SQL">
        <textarea
          required
          rows={8}
          value={form.sql_text}
          onChange={(e) => setForm({ ...form, sql_text: e.target.value })}
          aria-label="SQL"
          spellCheck={false}
          className={`${inputClass} font-mono text-xs`}
        />
      </Field>
      <Field label="What it does (plain language)">
        <Input required value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} aria-label="Description" />
      </Field>
      <fieldset className="space-y-1.5">
        <legend className="text-sm font-medium">Allowed roles</legend>
        <div className="flex flex-wrap gap-3">
          {BUSINESS_ROLES.map((role) => (
            <label key={role} className="inline-flex items-center gap-2 text-sm">
              <input type="checkbox" checked={form.allowed_roles.includes(role)} onChange={() => toggleRole(role)} className="size-4 accent-brand-600" />
              {ROLE_LABELS[role]}
            </label>
          ))}
        </div>
      </fieldset>
      <Field label="Metrics used" hint="Comma-separated metric names from the semantic layer, e.g. revenue (optional)">
        <Input value={metrics} onChange={(e) => setMetrics(e.target.value)} aria-label="Metrics used" />
      </Field>
      <div className="flex justify-end">
        <Button type="submit" loading={busy} disabled={form.allowed_roles.length === 0}>
          <BadgeCheck className="size-4" /> {draft.lineage_id ? "Save new version" : "Mark as verified"}
        </Button>
      </div>
    </form>
  );
}

function EvalCaseForm({ item, onDone }: { item: ReviewItem; onDone: (text: string) => void }) {
  const [caseType, setCaseType] = useState<(typeof CASE_TYPES)[number]>("medium");
  const [behaviour, setBehaviour] = useState<(typeof BEHAVIOURS)[number]>("correct_result");
  const [sql, setSql] = useState(item.sql_text ?? "");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const created = await api.post<{ case_key: string; dataset: string }>(`admin/feedback/${item.id}/eval-case`, {
        case_type: caseType,
        expected_behaviour: behaviour,
        expected_sql: sql.trim() || null,
      });
      onDone(`Evaluation case ${created.case_key} added to ${created.dataset}.`);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not create the case.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-4">
      {error && <Alert title="Not created">{error}</Alert>}
      <p className="text-sm">“{item.question}”</p>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Case type">
          <select className={inputClass} value={caseType} onChange={(e) => setCaseType(e.target.value as (typeof CASE_TYPES)[number])} aria-label="Case type">
            {CASE_TYPES.map((t) => (
              <option key={t} value={t}>
                {t.replace("_", " ")}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Expected behaviour">
          <select className={inputClass} value={behaviour} onChange={(e) => setBehaviour(e.target.value as (typeof BEHAVIOURS)[number])} aria-label="Expected behaviour">
            {BEHAVIOURS.map((b) => (
              <option key={b} value={b}>
                {b.replace("_", " ")}
              </option>
            ))}
          </select>
        </Field>
      </div>
      <Field label="Expected SQL (optional)" hint="Checked by the validator for the asking user's role.">
        <textarea rows={6} value={sql} onChange={(e) => setSql(e.target.value)} aria-label="Expected SQL" spellCheck={false} className={`${inputClass} font-mono text-xs`} />
      </Field>
      <div className="flex justify-end">
        <Button type="submit" loading={busy}>
          <FlaskConical className="size-4" /> Create evaluation case
        </Button>
      </div>
    </form>
  );
}

// --- queue -----------------------------------------------------------------------------

function Queue({ onNotice }: { onNotice: (notice: Notice) => void }) {
  const [kind, setKind] = useState<ReviewKind | "">("");
  const { data, error, loading, page, setPage, pageSize, reload } = usePaged<ReviewItem>("admin/review", { kind: kind || undefined }, 10);
  const [verify, setVerify] = useState<ReviewItem | null>(null);
  const [evalCase, setEvalCase] = useState<ReviewItem | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  async function rerun(item: ReviewItem) {
    setBusy(item.id);
    onNotice(null);
    try {
      const result = await api.post<{ status: string | null }>(`admin/errors/${item.id}/rerun`);
      onNotice({ tone: "green", text: `Re-run as ${item.username ?? "the original user"} finished: ${result.status ?? "unknown"}.` });
      reload();
    } catch (e) {
      onNotice({ tone: "red", text: e instanceof ApiError ? e.message : "Could not re-run." });
    } finally {
      setBusy(null);
    }
  }

  function done(text: string) {
    setVerify(null);
    setEvalCase(null);
    onNotice({ tone: "green", text });
    reload();
  }

  return (
    <>
      <div className="flex flex-wrap gap-2 px-5 pt-4">
        {(["", "not_helpful", "blocked", "failure"] as const).map((k) => (
          <button
            key={k || "all"}
            onClick={() => setKind(k)}
            className={`rounded-full px-3 py-1 text-xs font-medium ring-1 transition ${kind === k ? "bg-brand-600 text-white ring-brand-600" : "text-muted ring-[var(--border)] hover:text-[var(--text)]"}`}
          >
            {k ? KIND[k].label : "All"}
          </button>
        ))}
      </div>
      {error && (
        <div className="p-5">
          <Alert>{error}</Alert>
        </div>
      )}
      {loading && !data && <Skeleton className="m-5 h-24" />}
      {data && data.items.length === 0 && (
        <EmptyState icon={<BookCheck className="size-6" />} title="Nothing to review">
          Answers rated not helpful, blocked queries and open failures appear here.
        </EmptyState>
      )}
      {data && data.items.length > 0 && (
        <ul className="mt-3 divide-y divide-[var(--border)]" data-testid="review-queue">
          {data.items.map((item) => (
            <li key={`${item.kind}-${item.id}`} className="flex flex-wrap items-start gap-4 px-5 py-4">
              <div className="min-w-0 flex-1 space-y-1.5">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge tone={KIND[item.kind].tone}>
                    {KIND[item.kind].icon} {KIND[item.kind].label}
                  </Badge>
                  <span className="text-muted text-xs">
                    {item.username ?? "unknown"} · {item.role?.replace(/_/g, " ") ?? "no role"} · {formatDateTime(item.created_at)}
                  </span>
                </div>
                {item.question && <p className="text-sm font-medium">“{item.question}”</p>}
                <p className="text-muted break-words text-sm">{item.detail}</p>
                {item.sql_text && (
                  <details className="text-xs">
                    <summary className="text-muted cursor-pointer select-none">SQL</summary>
                    <pre className="mt-2 overflow-x-auto rounded-lg bg-slate-950 p-3 font-mono text-slate-100">{item.sql_text}</pre>
                  </details>
                )}
              </div>
              <div className="flex flex-wrap gap-2">
                {item.question && (item.kind === "not_helpful" || item.sql_text) && (
                  <Button variant="secondary" size="sm" onClick={() => setVerify(item)}>
                    <BadgeCheck className="size-3.5" /> Verify or correct
                  </Button>
                )}
                {item.kind === "not_helpful" && (
                  <Button variant="secondary" size="sm" onClick={() => setEvalCase(item)}>
                    <FlaskConical className="size-3.5" /> Make eval case
                  </Button>
                )}
                {item.kind === "failure" && (
                  <Button variant="secondary" size="sm" loading={busy === item.id} onClick={() => void rerun(item)}>
                    <RotateCw className="size-3.5" /> Re-run
                  </Button>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
      {data && <Pager page={page} pageSize={pageSize} total={data.total} onPage={setPage} />}

      {verify && (
        <Modal open title="Verify or correct the query" onClose={() => setVerify(null)}>
          <VerifyForm
            draft={{
              question_text: verify.question ?? "",
              sql_text: verify.sql_text ?? "",
              description: "",
              allowed_roles: isRole(verify.role) ? [verify.role] : [],
              metrics_used: [],
              source_question_id: verify.question_id,
              lineage_id: null,
            }}
            onDone={done}
          />
        </Modal>
      )}
      {evalCase && (
        <Modal open title="Turn into an evaluation case" onClose={() => setEvalCase(null)}>
          <EvalCaseForm item={evalCase} onDone={done} />
        </Modal>
      )}
    </>
  );
}

// --- library ---------------------------------------------------------------------------

function Library({ onNotice }: { onNotice: (notice: Notice) => void }) {
  const [active, setActive] = useState<"" | "true" | "false">("true");
  const { data, error, loading, page, setPage, pageSize, reload } = usePaged<VerifiedQuery>("admin/verified-queries", { is_active: active || undefined }, 10);
  const [correct, setCorrect] = useState<VerifiedQuery | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  async function toggle(query: VerifiedQuery) {
    setBusy(query.id);
    onNotice(null);
    try {
      await api.patch(`admin/verified-queries/${query.id}`, { is_active: !query.is_active });
      onNotice({ tone: "green", text: query.is_active ? "Example disabled; the agent no longer uses it." : "Example enabled again." });
      reload();
    } catch (e) {
      onNotice({ tone: "red", text: e instanceof ApiError ? e.message : "Could not change the example." });
    } finally {
      setBusy(null);
    }
  }

  return (
    <>
      <div className="flex flex-wrap gap-2 px-5 pt-4">
        {(
          [
            ["true", "Enabled"],
            ["false", "Disabled"],
            ["", "All versions"],
          ] as const
        ).map(([value, label]) => (
          <button
            key={label}
            onClick={() => setActive(value)}
            className={`rounded-full px-3 py-1 text-xs font-medium ring-1 transition ${active === value ? "bg-brand-600 text-white ring-brand-600" : "text-muted ring-[var(--border)] hover:text-[var(--text)]"}`}
          >
            {label}
          </button>
        ))}
      </div>
      {error && (
        <div className="p-5">
          <Alert>{error}</Alert>
        </div>
      )}
      {loading && !data && <Skeleton className="m-5 h-24" />}
      {data && data.items.length === 0 && <EmptyState icon={<BookCheck className="size-6" />} title="No examples" />}
      {data && data.items.length > 0 && (
        <ul className="mt-3 divide-y divide-[var(--border)]" data-testid="verified-library">
          {data.items.map((query) => (
            <li key={query.id} className="flex flex-wrap items-start gap-4 px-5 py-4">
              <div className="min-w-0 flex-1 space-y-1.5">
                <div className="flex flex-wrap items-center gap-2">
                  {query.is_active ? <Badge tone="green">Enabled</Badge> : <Badge>Disabled</Badge>}
                  <Badge tone="brand">v{query.version}</Badge>
                  {query.allowed_roles.map((role) => (
                    <Badge key={role}>{ROLE_LABELS[role]}</Badge>
                  ))}
                </div>
                <p className="text-sm font-medium">{query.question_text}</p>
                <p className="text-muted text-sm">{query.description}</p>
                <p className="text-muted text-xs">
                  Tables: {query.tables_used.join(", ") || "—"}
                  {query.metrics_used.length > 0 && ` · Metrics: ${query.metrics_used.join(", ")}`} · Verified by {query.verified_by ?? "unknown"}
                  {query.verified_at && ` · ${formatDateTime(query.verified_at)}`}
                </p>
                <details className="text-xs">
                  <summary className="text-muted cursor-pointer select-none">SQL</summary>
                  <pre className="mt-2 overflow-x-auto rounded-lg bg-slate-950 p-3 font-mono text-slate-100">{query.sql_text}</pre>
                </details>
              </div>
              <div className="flex flex-wrap gap-2">
                <Button variant="secondary" size="sm" onClick={() => setCorrect(query)}>
                  <Pencil className="size-3.5" /> Correct
                </Button>
                <Button variant="ghost" size="sm" loading={busy === query.id} onClick={() => void toggle(query)}>
                  {query.is_active ? "Disable" : "Enable"}
                </Button>
              </div>
            </li>
          ))}
        </ul>
      )}
      {data && <Pager page={page} pageSize={pageSize} total={data.total} onPage={setPage} />}
      {correct && (
        <Modal open title={`Correct example · new version of v${correct.version}`} onClose={() => setCorrect(null)}>
          <VerifyForm
            draft={{
              question_text: correct.question_text,
              sql_text: correct.sql_text,
              description: correct.description,
              allowed_roles: correct.allowed_roles,
              metrics_used: correct.metrics_used,
              source_question_id: correct.source_question_id,
              lineage_id: correct.lineage_id,
            }}
            onDone={(text) => {
              setCorrect(null);
              onNotice({ tone: "green", text });
              reload();
            }}
          />
        </Modal>
      )}
    </>
  );
}

export function ReviewBoard() {
  const [tab, setTab] = useState<"queue" | "library">("queue");
  const [notice, setNotice] = useState<Notice>(null);
  return (
    <div className="space-y-4">
      <div className="surface inline-flex rounded-xl p-1" role="tablist">
        {(
          [
            ["queue", "Review queue"],
            ["library", "Verified library"],
          ] as const
        ).map(([name, label]) => (
          <button
            key={name}
            role="tab"
            aria-selected={tab === name}
            onClick={() => {
              setTab(name);
              setNotice(null);
            }}
            className={`rounded-lg px-4 py-1.5 text-sm font-medium transition ${tab === name ? "bg-brand-600 text-white shadow-sm" : "text-muted hover:text-[var(--text)]"}`}
          >
            {label}
          </button>
        ))}
      </div>
      {notice && <Alert tone={notice.tone}>{notice.text}</Alert>}
      <Card className="overflow-hidden">{tab === "queue" ? <Queue onNotice={setNotice} /> : <Library onNotice={setNotice} />}</Card>
    </div>
  );
}
