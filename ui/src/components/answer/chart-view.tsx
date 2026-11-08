"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { formatCell, formatNumber, humanize } from "@/lib/format";
import type { ChartSpec } from "@/lib/types";
import { useNarrow } from "@/lib/use-narrow";

const SERIES = ["var(--chart-1)", "var(--chart-2)", "var(--chart-3)", "var(--chart-4)"];

function MetricCards({ spec }: { spec: ChartSpec }) {
  const row = spec.data[0] ?? {};
  const keys = spec.y.length ? spec.y : Object.keys(row);
  return (
    <div className="grid gap-3 sm:grid-cols-2" data-testid="chart-metric_card">
      {keys.map((key) => (
        <div key={key} className="rounded-xl bg-gradient-to-br from-brand-50 to-white p-5 ring-1 ring-brand-100 dark:from-brand-900/30 dark:to-transparent dark:ring-brand-900">
          <p className="text-muted text-xs font-medium uppercase tracking-wider">{humanize(key)}</p>
          <p className="mt-2 text-3xl font-semibold tabular-nums tracking-tight text-brand-700 dark:text-brand-200">
            {formatNumber(row[key])}
          </p>
        </div>
      ))}
    </div>
  );
}

/** Draws the API's neutral chart spec; the API decides the type (docs/answers-and-charts.md). */
export function ChartView({ spec }: { spec: ChartSpec | null }) {
  const narrow = useNarrow();
  if (!spec || spec.type === "none" || spec.data.length === 0) return null;
  if (spec.type === "metric_card") return <MetricCards spec={spec} />;

  const x = spec.x ?? "";
  const common = {
    data: spec.data,
    margin: { top: 8, right: 12, bottom: 4, left: 4 },
  };
  const axes = (
    <>
      <CartesianGrid strokeDasharray="3 3" stroke="var(--chart-grid)" vertical={false} />
      <XAxis dataKey={x} tickFormatter={(v) => formatCell(v)} tick={{ fontSize: 12, fill: "var(--text-muted)" }} tickLine={false} axisLine={{ stroke: "var(--chart-grid)" }} minTickGap={12} />
      <YAxis tickFormatter={(v) => formatNumber(v, true)} tick={{ fontSize: 12, fill: "var(--text-muted)" }} tickLine={false} axisLine={false} width={56} />
      <Tooltip
        formatter={(value, name) => [formatNumber(value), humanize(String(name))]}
        labelFormatter={(label) => formatCell(label)}
        contentStyle={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 12, fontSize: 12 }}
      />
      {spec.y.length > 1 && <Legend formatter={(value) => humanize(String(value))} wrapperStyle={{ fontSize: 12 }} />}
    </>
  );

  // On phones, category labels do not fit under vertical bars: draw the bars sideways.
  if (narrow && spec.type === "bar") {
    const label = (v: unknown) => {
      const text = formatCell(v);
      return text.length > 16 ? `${text.slice(0, 15)}…` : text;
    };
    return (
      <figure data-testid="chart-bar" data-layout="horizontal" className="space-y-2">
        {spec.title && <figcaption className="text-sm font-medium">{spec.title}</figcaption>}
        <div className="w-full" style={{ height: Math.min(56 + spec.data.length * 38, 520) }}>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={spec.data} layout="vertical" margin={{ top: 4, right: 12, bottom: 4, left: 4 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--chart-grid)" horizontal={false} />
              <XAxis type="number" tickFormatter={(v) => formatNumber(v, true)} tick={{ fontSize: 11, fill: "var(--text-muted)" }} tickLine={false} axisLine={false} />
              <YAxis type="category" dataKey={x} tickFormatter={label} tick={{ fontSize: 11, fill: "var(--text-muted)" }} tickLine={false} axisLine={false} width={104} interval={0} />
              <Tooltip
                formatter={(value, name) => [formatNumber(value), humanize(String(name))]}
                labelFormatter={(l) => formatCell(l)}
                contentStyle={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 12, fontSize: 12 }}
              />
              {spec.y.length > 1 && <Legend formatter={(value) => humanize(String(value))} wrapperStyle={{ fontSize: 11 }} />}
              {spec.y.map((key, i) => (
                <Bar key={key} dataKey={key} fill={SERIES[i % SERIES.length]} radius={[0, 6, 6, 0]} maxBarSize={26} />
              ))}
            </BarChart>
          </ResponsiveContainer>
        </div>
        <p className="text-muted text-xs">{spec.reason}</p>
      </figure>
    );
  }

  return (
    <figure data-testid={`chart-${spec.type}`} className="space-y-2">
      {spec.title && <figcaption className="text-sm font-medium">{spec.title}</figcaption>}
      <div className="h-72 w-full">
        <ResponsiveContainer width="100%" height="100%">
          {spec.type === "line" ? (
            <LineChart {...common}>
              {axes}
              {spec.y.map((key, i) => (
                <Line key={key} type="monotone" dataKey={key} stroke={SERIES[i % SERIES.length]} strokeWidth={2.5} dot={spec.data.length <= 24} activeDot={{ r: 5 }} />
              ))}
            </LineChart>
          ) : (
            <BarChart {...common}>
              {axes}
              {spec.y.map((key, i) => (
                <Bar key={key} dataKey={key} fill={SERIES[i % SERIES.length]} radius={[6, 6, 0, 0]} maxBarSize={48} />
              ))}
            </BarChart>
          )}
        </ResponsiveContainer>
      </div>
      <p className="text-muted text-xs">{spec.reason}</p>
    </figure>
  );
}
