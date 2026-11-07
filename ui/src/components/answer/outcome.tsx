import { AlertTriangle, Ban, ShieldAlert } from "lucide-react";
import type { ReactNode } from "react";

import type { AgentResponse } from "@/lib/types";

interface Outcome {
  icon: ReactNode;
  title: string;
  tip: string;
  tone: string;
}

const OUTCOMES: Record<"BLOCKED" | "REJECTED" | "FAILED", Outcome> = {
  BLOCKED: {
    icon: <ShieldAlert className="size-5" />,
    title: "This request was blocked",
    tip: "Only read-only questions about the data you are allowed to see can be answered. Try asking about revenue, orders, products or customers instead.",
    tone: "bg-amber-50 text-amber-900 ring-amber-200 dark:bg-amber-900/20 dark:text-amber-100 dark:ring-amber-900",
  },
  REJECTED: {
    icon: <Ban className="size-5" />,
    title: "This question can't be answered here",
    tip: "The assistant answers business questions about Northwind sales, products, customers and shipping.",
    tone: "bg-slate-100 text-slate-800 ring-slate-200 dark:bg-slate-800/60 dark:text-slate-100 dark:ring-slate-700",
  },
  FAILED: {
    icon: <AlertTriangle className="size-5" />,
    title: "Something went wrong answering this",
    tip: "Try rephrasing the question or narrowing the date range. If it keeps happening, share the reference below with support.",
    tone: "bg-rose-50 text-rose-900 ring-rose-200 dark:bg-rose-900/20 dark:text-rose-100 dark:ring-rose-900",
  },
};

export function isProblem(status: AgentResponse["status"]): status is "BLOCKED" | "REJECTED" | "FAILED" {
  return status === "BLOCKED" || status === "REJECTED" || status === "FAILED";
}

/** Friendly message for BLOCKED, REJECTED and FAILED results. */
export function OutcomeMessage({ response }: { response: AgentResponse }) {
  if (!isProblem(response.status)) return null;
  const outcome = OUTCOMES[response.status];
  return (
    <div className={`flex gap-3 rounded-xl p-4 ring-1 ${outcome.tone}`} role="status" data-testid={`outcome-${response.status}`}>
      <div className="mt-0.5 shrink-0">{outcome.icon}</div>
      <div className="space-y-1.5 text-sm">
        <p className="font-semibold">{outcome.title}</p>
        {(response.block?.message || response.message) && <p>{response.block?.message || response.message}</p>}
        <p className="opacity-80">{outcome.tip}</p>
        {response.block?.reason_code && (
          <p className="text-xs opacity-70">Reason: {response.block.reason_code.replace(/_/g, " ").toLowerCase()}</p>
        )}
      </div>
    </div>
  );
}
