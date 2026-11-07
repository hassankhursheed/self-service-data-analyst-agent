const NUMBER = new Intl.NumberFormat("en-GB", { maximumFractionDigits: 2 });
const COMPACT = new Intl.NumberFormat("en-GB", { notation: "compact", maximumFractionDigits: 1 });
const DATE = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", year: "numeric" });
const DATE_TIME = new Intl.DateTimeFormat("en-GB", {
  day: "numeric",
  month: "short",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
});

export function formatCell(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "number") return NUMBER.format(value);
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "string" && /^\d{4}-\d{2}-\d{2}(T|$)/.test(value)) {
    const date = new Date(value.length === 10 ? `${value}T00:00:00` : value);
    if (!Number.isNaN(date.getTime())) return DATE.format(date);
  }
  return String(value);
}

export function formatNumber(value: unknown, compact = false): string {
  if (typeof value !== "number") return formatCell(value);
  return compact ? COMPACT.format(value) : NUMBER.format(value);
}

export function formatDateTime(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? iso : DATE_TIME.format(date);
}

/** "total_revenue" -> "Total revenue" */
export function humanize(column: string): string {
  const text = column.replace(/_/g, " ").trim();
  return text.charAt(0).toUpperCase() + text.slice(1);
}
