"use client";

import { ChevronLeft, ChevronRight, Download } from "lucide-react";
import { useState } from "react";

import { api, ApiError } from "@/lib/api";
import { formatCell, humanize } from "@/lib/format";
import type { TablePage } from "@/lib/types";

import { Button } from "../ui";

/**
 * The result rows, one page at a time. For the latest question of a conversation, other
 * pages are loaded from the API; otherwise only the first page is available.
 */
export function ResultTable({ initial, conversationId }: { initial: TablePage; conversationId: string | null }) {
  const [table, setTable] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function go(page: number) {
    if (!conversationId) return;
    setBusy(true);
    setError(null);
    try {
      const body = await api.get<{ table: TablePage | null }>(
        `conversations/${conversationId}/table?page=${page}&page_size=${table.page_size}`,
      );
      if (body.table) setTable(body.table);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not load this page.");
    } finally {
      setBusy(false);
    }
  }

  const numeric = table.columns.map((_, i) => table.rows.some((row) => typeof row[i] === "number"));
  return (
    <div className="space-y-2">
      <div className="overflow-hidden rounded-xl border border-subtle">
        <div className="max-h-96 overflow-auto">
          <table className="w-full text-sm" data-testid="result-table">
            <thead className="bg-muted sticky top-0">
              <tr>
                {table.columns.map((column, i) => (
                  <th key={column} scope="col" className={`whitespace-nowrap px-3 py-2 text-xs font-semibold uppercase tracking-wider text-muted ${numeric[i] ? "text-right" : "text-left"}`}>
                    {humanize(column)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className={busy ? "opacity-50" : undefined}>
              {table.rows.map((row, r) => (
                <tr key={r} className="border-t border-subtle hover:bg-muted/60">
                  {row.map((cell, c) => (
                    <td key={c} className={`whitespace-nowrap px-3 py-2 ${numeric[c] ? "text-right tabular-nums" : ""}`}>
                      {formatCell(cell)}
                    </td>
                  ))}
                </tr>
              ))}
              {table.rows.length === 0 && (
                <tr>
                  <td colSpan={Math.max(1, table.columns.length)} className="text-muted px-3 py-6 text-center">
                    No rows matched.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
      <div className="text-muted flex flex-wrap items-center justify-between gap-2 text-xs">
        <span>
          {table.total_rows.toLocaleString("en-GB")} {table.total_rows === 1 ? "row" : "rows"}
          {table.truncated && " (limited by the row cap; narrow the question to see everything)"}
          {conversationId && table.total_rows > 0 && (
            <a
              href={`/api/proxy/conversations/${conversationId}/table.csv`}
              download
              className="ml-1 inline-flex min-h-9 items-center gap-1 rounded-lg px-2 font-medium text-brand-600 hover:bg-brand-50 hover:underline dark:text-brand-200 dark:hover:bg-brand-900/30"
              data-testid="download-csv"
            >
              <Download className="size-3.5" aria-hidden />
              Download CSV
            </a>
          )}
        </span>
        {table.total_pages > 1 && (
          <div className="flex items-center gap-2">
            {error && <span className="text-rose-600">{error}</span>}
            <span>
              Page {table.page} of {table.total_pages}
            </span>
            <Button variant="secondary" size="sm" aria-label="Previous page" disabled={!conversationId || busy || table.page <= 1} onClick={() => void go(table.page - 1)}>
              <ChevronLeft className="size-3.5" />
            </Button>
            <Button variant="secondary" size="sm" aria-label="Next page" disabled={!conversationId || busy || table.page >= table.total_pages} onClick={() => void go(table.page + 1)}>
              <ChevronRight className="size-3.5" />
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}
