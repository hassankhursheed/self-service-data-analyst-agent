"use client";

import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  Clock,
  Coins,
  FlaskConical,
  HelpCircle,
  KeyRound,
  MessageSquareText,
  RefreshCw,
  ShieldAlert,
  ThumbsUp,
  Wrench,
} from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { api, ApiError } from "@/lib/api";
import { formatDateTime, humanize } from "@/lib/format";
import { ROLE_LABELS, type RoleName } from "@/lib/types";

import { Alert, Button, Card, EmptyState, inputClass, Skeleton } from "../ui";

export interface Metrics {
  correlation_id: string;
  period_from: string;
  period_to: string;
  time_zone: string;
  questions: number;
  questions_by_role: Record<string, number>;
  outcomes: { answered: number; blocked: number; rejected: number; failed: number; awaiting_clarification: number; in_progress: number };
  blocked_by_reason: Record<string, number>;
  repair_attempts: number;
  repaired_runs: number;
  repair_success_rate: number | null;
  clarifications_asked: number;
  runs: number;
  latency_avg_ms: number | null;
  latency_p95_ms: number | null;
  input_tokens: number;
  output_tokens: number;
  cost_usd: string | number;
  feedback: { helpful: number; not_helpful: number };
  failed_logins: number;
  latest_eval_run: {
    run_id: string;
    experiment_name: string;
    status: string;
    execution_accuracy: string | number | null;
    unsafe_blocked_rate: string | number | null;
    access_leaks: number | null;
    started_at: string;
  } | null;
  daily: { date: string; questions: number; answered: number; blocked: number; rejected: number; failed: number; cost_usd: string | number }[];
  node_latency?: { node: string; label: string; steps: number; avg_ms: number; p95_ms: number }[];
}

type Preset = "today" | "7" | "30" | "custom";

function isoDay(date: Date): string {
  return date.toISOString().slice(0, 10);
}

function rangeFor(preset: Preset, custom: { from: string; to: string }): { from: string; to: string } {
  if (preset === "custom") return custom;
  const to = new Date();
  const from = new Date(to);
  from.setUTCDate(to.getUTCDate() - (preset === "today" ? 0 : Number(preset) - 1));
  return { from: isoDay(from), to: isoDay(to) };
}

const pct = (value: number | null) => (value === null ? "—" : `${(value * 100).toFixed(1)}%`);
const ms = (value: number | null) => (value === null ? "—" : value >= 1000 ? `${(value / 1000).toFixed(2)} s` : `${Math.round(value)} ms`);
const usd = (value: string | number) => `$${Number(value).toFixed(4)}`;
const int = (value: number) => value.toLocaleString("en-GB");

function Stat({ icon, label, value, hint, tone = "brand" }: { icon: ReactNode; label: string; value: string; hint?: string; tone?: "brand" | "green" | "amber" | "red" }) {
  const tones = {
    brand: "bg-brand-50 text-brand-600 dark:bg-brand-900/40 dark:text-brand-200",
    green: "bg-emerald-50 text-emerald-600 dark:bg-emerald-900/30 dark:text-emerald-300",
    amber: "bg-amber-50 text-amber-600 dark:bg-amber-900/30 dark:text-amber-300",
    red: "bg-rose-50 text-rose-600 dark:bg-rose-900/30 dark:text-rose-300",
  };
  return (
    <Card className="p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-muted text-xs font-medium uppercase tracking-wider">{label}</p>
          <p className="mt-1.5 text-2xl font-semibold tabular-nums tracking-tight" data-testid={`stat-${label}`}>
            {value}
          </p>
          {hint && <p className="text-muted mt-0.5 text-xs">{hint}</p>}
        </div>
        <div className={`rounded-xl p-2 ${tones[tone]}`}>{icon}</div>
      </div>
    </Card>
  );
}

function BarList({ title, items, empty }: { title: string; items: [string, number][]; empty: string }) {
  const max = Math.max(1, ...items.map(([, n]) => n));
  return (
    <Card className="p-5">
      <p className="text-sm font-semibold">{title}</p>
      {items.length === 0 ? (
        <p className="text-muted mt-3 text-sm">{empty}</p>
      ) : (
        <ul className="mt-3 space-y-2.5">
          {items.map(([label, n]) => (
            <li key={label} className="space-y-1">
              <div className="flex justify-between text-sm">
                <span>{label}</span>
                <span className="tabular-nums text-muted">{int(n)}</span>
              </div>
              <div className="h-2 rounded-full bg-slate-100 dark:bg-slate-800">
                <div className="h-2 rounded-full bg-brand-500" style={{ width: `${(n / max) * 100}%` }} />
              </div>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

export function MonitoringView({ metrics }: { metrics: Metrics }) {
  const o = metrics.outcomes;
  const finished = o.answered + o.blocked + o.rejected + o.failed;
  const rate = (n: number) => (finished ? n / finished : null);
  const ratings = metrics.feedback.helpful + metrics.feedback.not_helpful;
  const eval_ = metrics.latest_eval_run;
  const roles = Object.entries(metrics.questions_by_role).map(
    ([role, n]) => [ROLE_LABELS[role as RoleName] ?? humanize(role), n] as [string, number],
  );
  const reasons = Object.entries(metrics.blocked_by_reason).map(([reason, n]) => [humanize(reason.toLowerCase()), n] as [string, number]);

  return (
    <div className="space-y-6">
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Stat icon={<MessageSquareText className="size-4" />} label="Questions" value={int(metrics.questions)} hint={`${int(metrics.runs)} agent runs`} />
        <Stat icon={<CheckCircle2 className="size-4" />} tone="green" label="Answered" value={pct(rate(o.answered))} hint={`${int(o.answered)} of ${int(finished)} finished`} />
        <Stat icon={<ShieldAlert className="size-4" />} tone="amber" label="Blocked or rejected" value={pct(rate(o.blocked + o.rejected))} hint={`${int(o.blocked)} blocked · ${int(o.rejected)} rejected`} />
        <Stat icon={<AlertTriangle className="size-4" />} tone={o.failed ? "red" : "green"} label="Failure rate" value={pct(rate(o.failed))} hint={`${int(o.failed)} failed`} />
        <Stat icon={<Clock className="size-4" />} label="Latency p95" value={ms(metrics.latency_p95_ms)} hint={`average ${ms(metrics.latency_avg_ms)}`} />
        <Stat icon={<Coins className="size-4" />} label="Estimated cost" value={usd(metrics.cost_usd)} hint={`${int(metrics.input_tokens + metrics.output_tokens)} tokens (${int(metrics.input_tokens)} in · ${int(metrics.output_tokens)} out)`} />
        <Stat icon={<Wrench className="size-4" />} label="Repair success" value={pct(metrics.repair_success_rate)} hint={`${int(metrics.repair_attempts)} repair attempts in ${int(metrics.repaired_runs)} runs`} />
        <Stat icon={<HelpCircle className="size-4" />} label="Clarifications asked" value={int(metrics.clarifications_asked)} hint={`${int(o.awaiting_clarification)} still waiting for a reply`} />
        <Stat icon={<ThumbsUp className="size-4" />} tone="green" label="Helpful ratings" value={ratings ? pct(metrics.feedback.helpful / ratings) : "—"} hint={`${int(metrics.feedback.helpful)} helpful · ${int(metrics.feedback.not_helpful)} not helpful`} />
        <Stat icon={<KeyRound className="size-4" />} tone={metrics.failed_logins ? "red" : "green"} label="Failed logins" value={int(metrics.failed_logins)} />
        <Card className="p-4 sm:col-span-2">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <p className="text-muted text-xs font-medium uppercase tracking-wider">Latest evaluation run</p>
              {eval_ ? (
                <>
                  <p className="mt-1.5 truncate text-lg font-semibold">{eval_.experiment_name}</p>
                  <p className="text-muted text-xs">
                    {eval_.status} · {formatDateTime(eval_.started_at)} · accuracy{" "}
                    {eval_.execution_accuracy === null ? "—" : pct(Number(eval_.execution_accuracy))} · unsafe blocked{" "}
                    {eval_.unsafe_blocked_rate === null ? "—" : pct(Number(eval_.unsafe_blocked_rate))} · leaks {eval_.access_leaks ?? "—"}
                  </p>
                </>
              ) : (
                <p className="text-muted mt-1.5 text-sm">No evaluation run yet (Step 22).</p>
              )}
            </div>
            <div className="rounded-xl bg-brand-50 p-2 text-brand-600 dark:bg-brand-900/40 dark:text-brand-200">
              <FlaskConical className="size-4" />
            </div>
          </div>
        </Card>
      </div>

      <Card className="p-5">
        <p className="text-sm font-semibold">Outcomes per day</p>
        <p className="text-muted text-xs">Current outcome of the questions asked each day ({metrics.time_zone}).</p>
        <div className="mt-4 h-64" data-testid="daily-chart">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={metrics.daily} margin={{ top: 4, right: 8, bottom: 0, left: -12 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--chart-grid)" vertical={false} />
              <XAxis dataKey="date" tickFormatter={(d: string) => d.slice(5)} tick={{ fontSize: 12, fill: "var(--text-muted)" }} tickLine={false} axisLine={{ stroke: "var(--chart-grid)" }} />
              <YAxis allowDecimals={false} tick={{ fontSize: 12, fill: "var(--text-muted)" }} tickLine={false} axisLine={false} />
              <Tooltip contentStyle={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 12, fontSize: 12 }} />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              <Bar dataKey="answered" stackId="o" fill="#10b981" name="Answered" />
              <Bar dataKey="blocked" stackId="o" fill="#f59e0b" name="Blocked" />
              <Bar dataKey="rejected" stackId="o" fill="#94a3b8" name="Rejected" />
              <Bar dataKey="failed" stackId="o" fill="#f43f5e" name="Failed" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </Card>

      <Card className="p-5">
        <p className="text-sm font-semibold">Time per step</p>
        <p className="text-muted text-xs">Average and p95 time spent in each node of the agent, slowest first.</p>
        {(metrics.node_latency ?? []).length === 0 ? (
          <p className="text-muted mt-3 text-sm">No runs in this period.</p>
        ) : (
          <div className="mt-3 overflow-x-auto">
            <table className="w-full text-sm" data-testid="node-latency">
              <thead className="text-muted text-left text-xs uppercase tracking-wider">
                <tr>
                  <th className="py-2 pr-4 font-semibold">Step</th>
                  <th className="py-2 pr-4 text-right font-semibold">Runs</th>
                  <th className="py-2 pr-4 text-right font-semibold">Average</th>
                  <th className="py-2 text-right font-semibold">p95</th>
                </tr>
              </thead>
              <tbody>
                {(metrics.node_latency ?? []).map((n) => (
                  <tr key={n.node} className="border-t border-subtle">
                    <td className="py-2 pr-4">
                      <span className="text-muted font-mono text-xs">{n.node}</span> {n.label}
                    </td>
                    <td className="py-2 pr-4 text-right tabular-nums">{int(n.steps)}</td>
                    <td className="py-2 pr-4 text-right tabular-nums">{ms(n.avg_ms)}</td>
                    <td className="py-2 text-right tabular-nums">{ms(n.p95_ms)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <BarList title="Questions by role" items={roles} empty="No questions in this period." />
        <BarList title="Blocked queries by reason" items={reasons} empty="Nothing was blocked in this period." />
      </div>
    </div>
  );
}

export function MonitoringBoard() {
  const [preset, setPreset] = useState<Preset>("7");
  const [custom, setCustom] = useState(() => rangeFor("7", { from: "", to: "" }));
  const [nonce, setNonce] = useState(0);
  const [result, setResult] = useState<{ key: string; metrics?: Metrics; error?: string } | null>(null);
  const range = rangeFor(preset, custom);
  const key = `${range.from}|${range.to}|${nonce}`;

  useEffect(() => {
    let cancelled = false;
    api
      .get<Metrics>(`admin/metrics?from=${range.from}&to=${range.to}`)
      .then((metrics) => !cancelled && setResult({ key, metrics }))
      .catch((e: unknown) => !cancelled && setResult({ key, error: e instanceof ApiError ? e.message : "Could not load the metrics." }));
    return () => {
      cancelled = true;
    };
  }, [key, range.from, range.to]);

  const loading = result?.key !== key;
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-2">
        <div className="surface inline-flex rounded-xl p-1" role="tablist" aria-label="Period">
          {(
            [
              ["today", "Today"],
              ["7", "7 days"],
              ["30", "30 days"],
              ["custom", "Custom"],
            ] as const
          ).map(([value, label]) => (
            <button
              key={value}
              role="tab"
              aria-selected={preset === value}
              onClick={() => setPreset(value)}
              className={`rounded-lg px-3 py-1.5 text-sm font-medium transition ${preset === value ? "bg-brand-600 text-white shadow-sm" : "text-muted hover:text-[var(--text)]"}`}
            >
              {label}
            </button>
          ))}
        </div>
        {preset === "custom" && (
          <div className="flex items-center gap-2">
            <input type="date" aria-label="From" className={`${inputClass} w-auto`} value={custom.from} onChange={(e) => setCustom({ ...custom, from: e.target.value })} />
            <span className="text-muted text-sm">to</span>
            <input type="date" aria-label="To" className={`${inputClass} w-auto`} value={custom.to} onChange={(e) => setCustom({ ...custom, to: e.target.value })} />
          </div>
        )}
        <Button variant="ghost" size="sm" onClick={() => setNonce((n) => n + 1)} aria-label="Refresh">
          <RefreshCw className={`size-4 ${loading ? "animate-spin" : ""}`} />
        </Button>
      </div>

      {result?.error && !loading && <Alert title="Could not load the metrics">{result.error}</Alert>}
      {loading && !result?.metrics && (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {Array.from({ length: 8 }, (_, i) => (
            <Skeleton key={i} className="h-28" />
          ))}
        </div>
      )}
      {result?.metrics && (
        <div className={loading ? "opacity-60 transition-opacity" : undefined}>
          {result.metrics.questions === 0 && result.metrics.failed_logins === 0 && (
            <Card className="mb-5">
              <EmptyState icon={<Activity className="size-6" />} title="No activity in this period">
                Metrics appear as soon as users ask questions.
              </EmptyState>
            </Card>
          )}
          <MonitoringView metrics={result.metrics} />
        </div>
      )}
    </div>
  );
}
