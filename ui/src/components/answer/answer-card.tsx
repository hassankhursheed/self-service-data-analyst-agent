"use client";

import { AlertCircle, CalendarRange, Info, Lightbulb, Rows3 } from "lucide-react";

import type { AgentResponse } from "@/lib/types";

import { Badge } from "../ui";
import { ChartView } from "./chart-view";
import { Clarification } from "./clarification";
import { FeedbackBar } from "./feedback";
import { isProblem, OutcomeMessage } from "./outcome";
import { ResultTable } from "./result-table";
import { SqlPanel } from "./sql-panel";

export function AnswerCard({
  response,
  questionId,
  conversationId,
  isLatest,
  busy,
  onClarify,
}: {
  response: AgentResponse;
  questionId: string | null;
  conversationId: string | null;
  isLatest: boolean;
  busy: boolean;
  onClarify: (answer: string) => void;
}) {
  const answered = response.status === "ANSWERED";
  const waiting = response.status === "CLARIFICATION_NEEDED" && response.clarification;
  return (
    <div className="space-y-5" data-testid="answer-card" data-status={response.status ?? ""}>
      <OutcomeMessage response={response} />

      {waiting && response.clarification && (
        <Clarification
          question={response.clarification.question}
          options={response.clarification.options}
          busy={busy || !isLatest}
          onAnswer={onClarify}
        />
      )}

      {response.interpreted_as && (
        <p className="text-muted flex gap-2 text-sm">
          <Info className="mt-0.5 size-4 shrink-0" /> Interpreted as: <span className="font-medium text-[var(--text)]">{response.interpreted_as}</span>
        </p>
      )}

      {answered && response.answer && (
        <div className="space-y-2">
          {response.low_confidence && (
            <Badge tone="amber">
              <AlertCircle className="size-3" /> {response.low_confidence_label ?? "Low confidence"}
            </Badge>
          )}
          <p className="text-[15px] leading-relaxed">{response.answer}</p>
        </div>
      )}

      {answered && (response.date_range || response.row_count > 0) && (
        <div className="flex flex-wrap gap-2">
          {response.date_range && (
            <Badge tone="brand">
              <CalendarRange className="size-3" /> {response.date_range.label}
            </Badge>
          )}
          <Badge>
            <Rows3 className="size-3" /> {response.row_count.toLocaleString("en-GB")} {response.row_count === 1 ? "row" : "rows"}
          </Badge>
        </div>
      )}

      {answered && <ChartView spec={response.chart} />}

      {answered && response.table && <ResultTable initial={response.table} conversationId={isLatest ? conversationId : null} />}

      {(response.assumptions.length > 0 || response.notices.filter((n) => !n.startsWith("Interpreted as")).length > 0) && !isProblem(response.status) && (
        <div className="space-y-1.5 rounded-xl bg-muted p-4 text-sm">
          <p className="flex items-center gap-2 font-medium">
            <Lightbulb className="size-4 text-amber-500" /> Assumptions and notes
          </p>
          <ul className="text-muted list-disc space-y-1 pl-6">
            {response.assumptions.map((item) => (
              <li key={`a-${item}`}>{item}</li>
            ))}
            {response.notices
              .filter((n) => !n.startsWith("Interpreted as"))
              .map((item) => (
                <li key={`n-${item}`}>{item}</li>
              ))}
          </ul>
        </div>
      )}

      {answered && response.sql.text && <SqlPanel sql={response.sql.text} description={response.sql.description} />}

      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-subtle pt-4">
        {questionId && (answered || isProblem(response.status)) ? <FeedbackBar questionId={questionId} /> : <span />}
        {response.correlation_id && (
          <span className="text-muted font-mono text-[11px]" title="Reference for support">
            ref {response.correlation_id.slice(0, 8)}
          </span>
        )}
      </div>
    </div>
  );
}
