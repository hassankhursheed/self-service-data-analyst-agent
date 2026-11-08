import { formatNumber, humanize } from "@/lib/format";
import type { AnswerItem } from "@/lib/types";

/**
 * The answer's rows as a ranked list under the summary: rank, name, value, a bar for its
 * size and an optional detail. The items come from the API as structured output and were
 * checked against the query result there.
 */
export function RankedResults({ items, valueLabel }: { items: AnswerItem[]; valueLabel?: string | null }) {
  const max = Math.max(...items.map((item) => Math.abs(item.value ?? 0)), 0) || 1;
  const hasValues = items.some((item) => item.value !== null && item.value !== undefined);
  return (
    <figure className="space-y-2" data-testid="ranked-results">
      {hasValues && valueLabel && (
        <figcaption className="text-muted text-right text-xs font-medium uppercase tracking-wider">{humanize(valueLabel)}</figcaption>
      )}
      <ol className="space-y-2">
        {items.map((item, index) => (
          <li key={`${item.label}-${index}`} className="rounded-xl border border-subtle px-3 py-2.5" data-testid="ranked-item">
            <div className="flex items-center gap-3">
              <span
                className={`flex size-7 shrink-0 items-center justify-center rounded-full text-xs font-semibold ${
                  index === 0 ? "bg-brand-600 text-white" : "bg-brand-50 text-brand-700 dark:bg-brand-900/40 dark:text-brand-200"
                }`}
                aria-label={`Rank ${index + 1}`}
              >
                {index + 1}
              </span>
              <span className="min-w-0 flex-1 truncate text-sm font-medium" title={item.label}>
                {item.label}
              </span>
              {item.value !== null && item.value !== undefined && (
                <span className="shrink-0 text-sm font-semibold tabular-nums">{formatNumber(item.value)}</span>
              )}
            </div>
            {hasValues && item.value !== null && item.value !== undefined && (
              <div className="ml-10 mt-2 h-1.5 overflow-hidden rounded-full bg-muted" aria-hidden>
                <div className="h-full rounded-full bg-brand-500" style={{ width: `${Math.max(2, (Math.abs(item.value) / max) * 100)}%` }} />
              </div>
            )}
            {item.detail && <p className="text-muted ml-10 mt-1.5 text-xs">{item.detail}</p>}
          </li>
        ))}
      </ol>
    </figure>
  );
}
