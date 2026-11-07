"use client";

import { Check, ChevronDown, Code2, Copy } from "lucide-react";
import { useState } from "react";

export function SqlPanel({ sql, description }: { sql: string; description: string | null }) {
  const [open, setOpen] = useState(false);
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(sql);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard not available */
    }
  }

  return (
    <div className="rounded-xl border border-subtle">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        className="flex w-full items-start gap-3 px-4 py-3 text-left"
      >
        <Code2 className="mt-0.5 size-4 shrink-0 text-brand-600 dark:text-brand-400" />
        <span className="min-w-0 flex-1">
          <span className="block text-sm font-medium">How this was calculated</span>
          <span className="text-muted block text-sm">{description ?? "The SQL query that produced this answer."}</span>
        </span>
        <ChevronDown className={`text-muted mt-0.5 size-4 shrink-0 transition-transform ${open ? "rotate-180" : ""}`} />
      </button>
      {open && (
        <div className="relative border-t border-subtle">
          <button
            type="button"
            onClick={() => void copy()}
            className="text-muted absolute right-2 top-2 inline-flex items-center gap-1 rounded-md bg-slate-800/80 px-2 py-1 text-xs text-slate-200 hover:bg-slate-700"
          >
            {copied ? <Check className="size-3" /> : <Copy className="size-3" />}
            {copied ? "Copied" : "Copy"}
          </button>
          <pre className="overflow-x-auto rounded-b-xl bg-slate-950 p-4 pr-20 font-mono text-xs leading-relaxed text-slate-100">
            <code>{sql}</code>
          </pre>
        </div>
      )}
    </div>
  );
}
