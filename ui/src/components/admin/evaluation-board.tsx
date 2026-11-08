"use client";

import { CheckCircle2, ChevronLeft, FlaskConical, Play, RefreshCw, ShieldAlert, XCircle } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";

import { api, ApiError } from "@/lib/api";
import { formatCell, formatDateTime, humanize } from "@/lib/format";

import { Alert, Badge, Button, Card, EmptyState, Field, Input, inputClass, Skeleton, type Tone } from "../ui";

export interface RunSummary {
  run_id: string;
  experiment_name: string;
  model_name: string;
  status: "running" | "completed" | "failed";
  semantic_version: string;
  verified_examples_enabled: boolean;
  cases_total: number | null;
  cases_passed: number | null;
  execution_accuracy: string | number | null;
  clarification_rate: string | number | null;
  unsafe_blocked_rate: string | number | null;
  access_leaks: number | null;
  ungrounded_answers: number | null;
  latency_p50_ms: number | null;
  latency_p95_ms: number | null;
  avg_cost_usd: string | number | null;
  started_at: string;
  finished_at: string | null;
  error_message: string | null;
  settings: Record<string, unknown>;
  progress: number;
}

interface Preview {
  columns: string[];
  rows: unknown[][];
  row_count: number;
}

export interface CaseResult {
  case_key: string;
  case_type: string;
  question: string;
  test_user: string;
  expected_behaviour: string;
  passed: boolean;
  final_status: string | null;
  failure_reason: string | null;
  leaked: boolean;
  ungrounded: boolean;
  latency_ms: number | null;
  details: { sql?: string | null; answer?: string | null; expected?: Preview | null; actual?: Preview | null; ungrounded_numbers?: string[] };
}

type Targets = Record<string, number>;

const CASE_TYPES = ["simple", "medium", "hard", "ambiguous", "unsafe", "access_control"] as const;

const num = (v: string | number | null) => (v === null ? null : Number(v));
const pct = (v: string | number | null) => (v === null ? "—" : `${(Number(v) * 100).toFixed(1)}%`);

/** Rows of the comparison table: label, value getter, formatter and whether it meets the target. */
export const METRICS: {
  key: keyof RunSummary;
  label: string;
  format: (r: RunSummary) => string;
  ok?: (r: RunSummary, t: Targets) => boolean | null;
}[] = [
  { key: "execution_accuracy", label: "Execution accuracy", format: (r) => pct(r.execution_accuracy), ok: (r, t) => (num(r.execution_accuracy) === null ? null : num(r.execution_accuracy)! >= (t.execution_accuracy ?? 0)) },
  { key: "clarification_rate", label: "Clarification rate", format: (r) => pct(r.clarification_rate), ok: (r, t) => (num(r.clarification_rate) === null ? null : num(r.clarification_rate)! >= (t.clarification_rate ?? 0)) },
  { key: "unsafe_blocked_rate", label: "Unsafe blocked", format: (r) => pct(r.unsafe_blocked_rate), ok: (r, t) => (num(r.unsafe_blocked_rate) === null ? null : num(r.unsafe_blocked_rate)! >= (t.unsafe_blocked_rate ?? 1)) },
  { key: "access_leaks", label: "Access leaks", format: (r) => String(r.access_leaks ?? "—"), ok: (r, t) => (r.access_leaks === null ? null : r.access_leaks <= (t.access_leaks ?? 0)) },
  { key: "ungrounded_answers", label: "Ungrounded answers", format: (r) => String(r.ungrounded_answers ?? "—"), ok: (r, t) => (r.ungrounded_answers === null ? null : r.ungrounded_answers <= (t.ungrounded_answers ?? 0)) },
  { key: "latency_p50_ms", label: "Latency p50 / p95", format: (r) => (r.latency_p50_ms === null ? "—" : `${(r.latency_p50_ms / 1000).toFixed(1)} / ${((r.latency_p95_ms ?? 0) / 1000).toFixed(1)} s`) },
  { key: "avg_cost_usd", label: "Avg cost / question", format: (r) => (r.avg_cost_usd === null ? "—" : `$${Number(r.avg_cost_usd).toFixed(5)}`) },
  { key: "cases_passed", label: "Cases passed", format: (r) => `${r.cases_passed ?? "—"} / ${r.cases_total ?? "—"}` },
];

function statusBadge(run: RunSummary) {
  const tone: Tone = run.status === "completed" ? "green" : run.status === "failed" ? "red" : "amber";
  const label = run.status === "running" ? `running ${run.progress}/${run.cases_total ?? "?"}` : run.status;
  return <Badge tone={tone}>{label}</Badge>;
}

function Mark({ ok }: { ok: boolean | null | undefined }) {
  if (ok === null || ok === undefined) return null;
  return ok ? <CheckCircle2 className="inline size-3.5 text-emerald-500" aria-label="meets target" /> : <XCircle className="inline size-3.5 text-rose-500" aria-label="misses target" />;
}

function StartForm({ disabled, onStarted }: { disabled: boolean; onStarted: () => void }) {
  const [name, setName] = useState("with-verified-examples");
  const [verified, setVerified] = useState(true);
  const [semantic, setSemantic] = useState<"full" | "names_only">("full");
  const [types, setTypes] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.post("admin/eval/run", {
        dataset: "northwind-eval",
        experiment_name: name.trim(),
        verified_examples_enabled: verified,
        semantic_mode: semantic,
        case_types: types.length ? types : null,
      });
      onStarted();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not start the run.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="p-5">
      <form onSubmit={submit} className="space-y-4">
        <p className="text-sm font-semibold">Start an evaluation run</p>
        {error && <Alert>{error}</Alert>}
        <div className="grid gap-4 md:grid-cols-3">
          <Field label="Experiment name">
            <Input value={name} onChange={(e) => setName(e.target.value)} required maxLength={100} aria-label="Experiment name" />
          </Field>
          <Field label="Semantic layer">
            <select className={inputClass} value={semantic} onChange={(e) => setSemantic(e.target.value as "full" | "names_only")} aria-label="Semantic layer">
              <option value="full">Full (descriptions, metrics, synonyms)</option>
              <option value="names_only">Names only</option>
            </select>
          </Field>
          <label className="flex items-center gap-2 self-end pb-2 text-sm">
            <input type="checkbox" checked={verified} onChange={(e) => setVerified(e.target.checked)} className="size-4 accent-brand-600" />
            Use verified examples
          </label>
        </div>
        <fieldset className="space-y-1.5">
          <legend className="text-sm font-medium">Case types (none selected = all 60 cases)</legend>
          <div className="flex flex-wrap gap-3">
            {CASE_TYPES.map((t) => (
              <label key={t} className="inline-flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={types.includes(t)}
                  onChange={() => setTypes((all) => (all.includes(t) ? all.filter((x) => x !== t) : [...all, t]))}
                  className="size-4 accent-brand-600"
                />
                {humanize(t)}
              </label>
            ))}
          </div>
        </fieldset>
        <div className="flex items-center justify-between gap-3">
          <p className="text-muted text-xs">Runs every case as its test user with the pinned model at temperature 0. Takes several minutes and calls the real model.</p>
          <Button type="submit" loading={busy} disabled={disabled}>
            <Play className="size-4" /> Run
          </Button>
        </div>
      </form>
    </Card>
  );
}

function PreviewTable({ title, data }: { title: string; data: Preview | null | undefined }) {
  return (
    <div className="min-w-0 space-y-1">
      <p className="text-muted text-xs font-medium uppercase tracking-wider">{title}</p>
      {!data ? (
        <p className="text-muted text-xs">—</p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-subtle">
          <table className="w-full text-xs">
            <thead className="bg-muted">
              <tr>
                {data.columns.map((c) => (
                  <th key={c} className="whitespace-nowrap px-2 py-1 text-left font-semibold">
                    {c}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.rows.map((row, i) => (
                <tr key={i} className="border-t border-subtle">
                  {row.map((cell, j) => (
                    <td key={j} className="whitespace-nowrap px-2 py-1 tabular-nums">
                      {formatCell(cell)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
          {data.row_count > data.rows.length && <p className="text-muted px-2 py-1 text-xs">… {data.row_count} rows in total</p>}
        </div>
      )}
    </div>
  );
}

export function CaseRow({ result }: { result: CaseResult }) {
  return (
    <details className="group px-5 py-3" data-testid={`case-${result.case_key}`}>
      <summary className="flex cursor-pointer list-none flex-wrap items-center gap-2">
        {result.passed ? <CheckCircle2 className="size-4 text-emerald-500" /> : <XCircle className="size-4 text-rose-500" />}
        <span className="font-mono text-xs">{result.case_key}</span>
        <Badge>{humanize(result.case_type)}</Badge>
        {result.leaked && (
          <Badge tone="red">
            <ShieldAlert className="size-3" /> leak
          </Badge>
        )}
        {result.ungrounded && <Badge tone="amber">ungrounded</Badge>}
        <span className="min-w-0 flex-1 truncate text-sm">{result.question}</span>
        <span className="text-muted text-xs">{result.final_status ?? "—"}</span>
      </summary>
      <div className="mt-3 space-y-3 pl-6 text-sm">
        <p className="text-muted">
          As <span className="font-medium text-[var(--text)]">{result.test_user}</span> · expected {humanize(result.expected_behaviour)} · {result.failure_reason ?? "passed"} · {result.latency_ms ?? "—"} ms
        </p>
        {result.details.answer && <p>{result.details.answer}</p>}
        {result.details.ungrounded_numbers && result.details.ungrounded_numbers.length > 0 && (
          <p className="text-xs text-amber-700 dark:text-amber-300">Numbers not found in the result: {result.details.ungrounded_numbers.join(", ")}</p>
        )}
        {result.details.sql && <pre className="overflow-x-auto rounded-lg bg-slate-950 p-3 font-mono text-xs text-slate-100">{result.details.sql}</pre>}
        <div className="grid gap-3 lg:grid-cols-2">
          <PreviewTable title="Expected" data={result.details.expected} />
          <PreviewTable title="Actual" data={result.details.actual} />
        </div>
      </div>
    </details>
  );
}

function RunDetail({ runId, targets, onBack }: { runId: string; targets: Targets; onBack: () => void }) {
  const [data, setData] = useState<{ run: RunSummary; results: CaseResult[] } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    let cancelled = false;
    api
      .get<{ run: RunSummary; results: CaseResult[] }>(`admin/eval/runs/${runId}`)
      .then((d) => !cancelled && setData(d))
      .catch((e: unknown) => !cancelled && setError(e instanceof ApiError ? e.message : "Could not load the run."));
    return () => {
      cancelled = true;
    };
  }, [runId, nonce]);

  useEffect(() => {
    if (data?.run.status !== "running") return;
    const timer = setInterval(() => setNonce((n) => n + 1), 4000);
    return () => clearInterval(timer);
  }, [data?.run.status]);

  if (error) return <Alert>{error}</Alert>;
  if (!data) return <Skeleton className="h-64" />;
  const failing = data.results.filter((r) => !r.passed);
  const passing = data.results.filter((r) => r.passed);
  return (
    <div className="space-y-5">
      <Button variant="ghost" size="sm" onClick={onBack}>
        <ChevronLeft className="size-4" /> All runs
      </Button>
      <Card className="p-5">
        <div className="flex flex-wrap items-center gap-3">
          <p className="text-lg font-semibold">{data.run.experiment_name}</p>
          {statusBadge(data.run)}
        </div>
        <p className="text-muted mt-1 text-xs">
          {data.run.model_name} · semantic {data.run.semantic_version} · verified examples {data.run.verified_examples_enabled ? "on" : "off"} · {formatDateTime(data.run.started_at)}
        </p>
        {data.run.error_message && (
          <div className="mt-3">
            <Alert>{data.run.error_message}</Alert>
          </div>
        )}
        <dl className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {METRICS.map((m) => (
            <div key={m.key} className="rounded-xl bg-muted p-3">
              <dt className="text-muted text-xs">{m.label}</dt>
              <dd className="mt-1 flex items-center gap-1.5 text-lg font-semibold tabular-nums">
                {m.format(data.run)} <Mark ok={m.ok?.(data.run, targets)} />
              </dd>
            </div>
          ))}
        </dl>
      </Card>
      <Card className="overflow-hidden">
        <p className="border-b border-subtle px-5 py-3 text-sm font-semibold">Failing cases ({failing.length})</p>
        {failing.length === 0 ? <p className="text-muted px-5 py-4 text-sm">None.</p> : <div className="divide-y divide-[var(--border)]">{failing.map((r) => <CaseRow key={r.case_key} result={r} />)}</div>}
      </Card>
      <Card className="overflow-hidden">
        <p className="border-b border-subtle px-5 py-3 text-sm font-semibold">Passing cases ({passing.length})</p>
        <div className="divide-y divide-[var(--border)]">
          {passing.map((r) => (
            <CaseRow key={r.case_key} result={r} />
          ))}
        </div>
      </Card>
    </div>
  );
}

export function Comparison({ runs, targets }: { runs: RunSummary[]; targets: Targets }) {
  return (
    <Card className="overflow-x-auto">
      <table className="w-full text-sm" data-testid="comparison">
        <thead className="bg-muted text-left text-xs uppercase tracking-wider text-muted">
          <tr>
            <th className="px-4 py-3 font-semibold">Metric</th>
            {runs.map((r) => (
              <th key={r.run_id} className="px-4 py-3 font-semibold normal-case">
                {r.experiment_name}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {METRICS.map((m) => (
            <tr key={m.key} className="border-t border-subtle">
              <td className="px-4 py-2.5">{m.label}</td>
              {runs.map((r) => (
                <td key={r.run_id} className="px-4 py-2.5 tabular-nums">
                  <span className="inline-flex items-center gap-1.5">
                    {m.format(r)} <Mark ok={m.ok?.(r, targets)} />
                  </span>
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
  );
}

export function EvaluationBoard() {
  const [data, setData] = useState<{ items: RunSummary[]; targets: Targets } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);
  const [open, setOpen] = useState<string | null>(null);
  const [compare, setCompare] = useState<string[]>([]);

  useEffect(() => {
    let cancelled = false;
    api
      .get<{ items: RunSummary[]; targets: Targets }>("admin/eval/runs?page_size=50")
      .then((d) => !cancelled && setData(d))
      .catch((e: unknown) => !cancelled && setError(e instanceof ApiError ? e.message : "Could not load the runs."));
    return () => {
      cancelled = true;
    };
  }, [nonce]);

  const running = data?.items.some((r) => r.status === "running") ?? false;
  useEffect(() => {
    if (!running) return;
    const timer = setInterval(() => setNonce((n) => n + 1), 4000);
    return () => clearInterval(timer);
  }, [running]);

  if (open && data) return <RunDetail runId={open} targets={data.targets} onBack={() => setOpen(null)} />;
  const compared = data?.items.filter((r) => compare.includes(r.run_id)) ?? [];

  return (
    <div className="space-y-5">
      <StartForm disabled={running} onStarted={() => setNonce((n) => n + 1)} />
      {error && <Alert title="Could not load the runs">{error}</Alert>}
      {!data && !error && <Skeleton className="h-40" />}
      {data && data.items.length === 0 && (
        <Card>
          <EmptyState icon={<FlaskConical className="size-6" />} title="No evaluation runs yet">
            Start a run above, or from the command line: python -m eval.run_eval --experiment NAME
          </EmptyState>
        </Card>
      )}
      {data && data.items.length > 0 && (
        <Card className="overflow-hidden">
          <div className="flex items-center justify-between border-b border-subtle px-5 py-3">
            <p className="text-sm font-semibold">Runs</p>
            <Button variant="ghost" size="sm" onClick={() => setNonce((n) => n + 1)} aria-label="Refresh">
              <RefreshCw className="size-4" />
            </Button>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm" data-testid="runs-table">
              <thead className="bg-muted text-left text-xs uppercase tracking-wider text-muted">
                <tr>
                  <th className="px-4 py-3 font-semibold">Compare</th>
                  <th className="px-4 py-3 font-semibold">Experiment</th>
                  <th className="px-4 py-3 font-semibold">Status</th>
                  <th className="px-4 py-3 font-semibold">Accuracy</th>
                  <th className="px-4 py-3 font-semibold">Clarify</th>
                  <th className="px-4 py-3 font-semibold">Unsafe</th>
                  <th className="px-4 py-3 font-semibold">Leaks</th>
                  <th className="px-4 py-3 font-semibold">Started</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((r) => (
                  <tr key={r.run_id} className="border-t border-subtle hover:bg-muted/50">
                    <td className="px-4 py-2.5">
                      <input
                        type="checkbox"
                        aria-label={`Compare ${r.experiment_name}`}
                        checked={compare.includes(r.run_id)}
                        onChange={() => setCompare((all) => (all.includes(r.run_id) ? all.filter((x) => x !== r.run_id) : [...all, r.run_id].slice(-3)))}
                        className="size-4 accent-brand-600"
                      />
                    </td>
                    <td className="px-4 py-2.5">
                      <button className="font-medium text-brand-700 hover:underline dark:text-brand-300" onClick={() => setOpen(r.run_id)}>
                        {r.experiment_name}
                      </button>
                      <p className="text-muted text-xs">
                        {r.semantic_version} · examples {r.verified_examples_enabled ? "on" : "off"}
                      </p>
                    </td>
                    <td className="px-4 py-2.5">{statusBadge(r)}</td>
                    <td className="px-4 py-2.5 tabular-nums">{pct(r.execution_accuracy)}</td>
                    <td className="px-4 py-2.5 tabular-nums">{pct(r.clarification_rate)}</td>
                    <td className="px-4 py-2.5 tabular-nums">{pct(r.unsafe_blocked_rate)}</td>
                    <td className="px-4 py-2.5 tabular-nums">{r.access_leaks ?? "—"}</td>
                    <td className="text-muted whitespace-nowrap px-4 py-2.5 text-xs">{formatDateTime(r.started_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
      {compared.length >= 2 && <Comparison runs={compared} targets={data!.targets} />}
      {compared.length === 1 && <p className="text-muted text-sm">Select one more run to compare.</p>}
    </div>
  );
}
