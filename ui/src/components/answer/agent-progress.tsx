"use client";

import clsx from "clsx";
import { Check, Loader2 } from "lucide-react";
import { useEffect, useState } from "react";

// The agent's stages (docs/design): what happens to every question. The API answers in
// one response, so the steps advance on a typical timing; the last one stays active until
// the answer arrives, so the list never claims a step finished before it did.
export const AGENT_STEPS = [
  "Understanding your question",
  "Writing a read-only SQL query",
  "Checking safety and your access",
  "Running it on the database",
  "Explaining the result",
] as const;

const STEP_AFTER_MS = [0, 2500, 5000, 6000, 7000];

export function AgentProgress({ startedAt }: { startedAt: number }) {
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    const timer = window.setInterval(() => setElapsed(Date.now() - startedAt), 400);
    return () => window.clearInterval(timer);
  }, [startedAt]);

  const active = STEP_AFTER_MS.filter((ms) => elapsed >= ms).length - 1;
  return (
    <div aria-live="polite" data-testid="agent-progress">
      <ol className="space-y-2.5">
        {AGENT_STEPS.map((step, index) => {
          const done = index < active;
          const current = index === active;
          return (
            <li key={step} className="flex items-center gap-3 text-sm">
              <span
                className={clsx(
                  "flex size-6 shrink-0 items-center justify-center rounded-full border",
                  done && "border-brand-500 bg-brand-500 text-white",
                  current && "border-brand-400 text-brand-600 dark:text-brand-400",
                  !done && !current && "border-subtle text-muted",
                )}
              >
                {done ? <Check className="size-3.5" /> : current ? <Loader2 className="size-3.5 animate-spin" /> : <span className="size-1.5 rounded-full bg-current" />}
              </span>
              <span className={clsx(done && "text-muted", current && "font-medium animate-step", !done && !current && "text-muted opacity-60")}>{step}</span>
            </li>
          );
        })}
      </ol>
      {elapsed > 15000 && (
        <p className="text-muted mt-4 text-xs">Still working. When the AI service is busy, a question can take up to a minute.</p>
      )}
    </div>
  );
}
