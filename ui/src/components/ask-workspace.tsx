"use client";

import { ArrowUp, MessageSquarePlus, Sparkles } from "lucide-react";
import { useEffect, useRef, useState, type KeyboardEvent } from "react";

import { api, ApiError } from "@/lib/api";
import type { AgentResponse, AskResponse, ConversationDetail, RoleName } from "@/lib/types";

import { AnswerCard } from "./answer/answer-card";
import { Alert, Badge, Button, Card, Skeleton } from "./ui";

// The question limit (config/sql_policy.yaml max_question_length; a test keeps them equal).
export const MAX_QUESTION_CHARS = 500;
const MAX_CHARS = MAX_QUESTION_CHARS;

const EXAMPLES: Record<string, string[]> = {
  sales_manager: [
    "What was our revenue last quarter?",
    "Top 5 products by revenue in 2024",
    "Monthly revenue in 2024",
    "Which customers ordered the most this year?",
  ],
  finance_analyst: [
    "Total revenue by country in 2024",
    "Average order value by month in 2024",
    "Revenue last quarter compared with the quarter before",
    "Top 10 customers by revenue in 2024",
  ],
  operations_manager: [
    "Average shipping days by shipper in 2024",
    "How many orders were shipped late last month?",
    "Number of orders by shipper this year",
    "Products that are below their reorder level",
  ],
};

interface Turn {
  key: string;
  question: string;
  status?: string;
  response?: AgentResponse;
  questionId: string | null;
  error?: string;
  pending?: boolean;
}

function statusTone(status: string | undefined) {
  if (status === "ANSWERED") return "green" as const;
  if (status === "BLOCKED" || status === "FAILED") return "red" as const;
  if (status === "REJECTED") return "neutral" as const;
  return "amber" as const;
}

export function AskWorkspace({ role, conversationId: initialId }: { role: RoleName | null; conversationId: string | null }) {
  const [conversationId, setConversationId] = useState<string | null>(initialId);
  const [title, setTitle] = useState<string | null>(null);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(Boolean(initialId));
  const [loadError, setLoadError] = useState<string | null>(null);
  const bottom = useRef<HTMLDivElement>(null);

  // Reopen a conversation from History.
  useEffect(() => {
    if (!initialId) return;
    let cancelled = false;
    api
      .get<ConversationDetail>(`conversations/${initialId}`)
      .then((detail) => {
        if (cancelled) return;
        setTitle(detail.title);
        setTurns(
          detail.questions.map((q, i) => ({
            key: q.id,
            question: q.question,
            status: q.status,
            questionId: q.id,
            response: i === detail.questions.length - 1 && detail.latest ? detail.latest : undefined,
          })),
        );
      })
      .catch((e) => !cancelled && setLoadError(e instanceof ApiError ? e.message : "Could not open this conversation."))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [initialId]);

  useEffect(() => {
    bottom.current?.scrollIntoView?.({ behavior: "smooth", block: "end" });
  }, [turns.length]);

  function update(key: string, patch: Partial<Turn>) {
    setTurns((all) => all.map((turn) => (turn.key === key ? { ...turn, ...patch } : turn)));
  }

  async function ask(question: string) {
    const trimmed = question.trim();
    if (!trimmed || busy) return;
    const key = crypto.randomUUID();
    setTurns((all) => [...all, { key, question: trimmed, questionId: null, pending: true }]);
    setText("");
    setBusy(true);
    try {
      const response = await api.post<AskResponse>("ask", { question: trimmed, conversation_id: conversationId });
      update(key, { response, status: response.status ?? undefined, questionId: response.question_id, pending: false });
      if (!conversationId) {
        setConversationId(response.conversation_id);
        setTitle(trimmed.slice(0, 80));
        // Keep the URL shareable without remounting this page.
        window.history.replaceState(null, "", `/?c=${response.conversation_id}`);
      }
    } catch (e) {
      update(key, { pending: false, error: e instanceof ApiError ? e.message : "Something went wrong." });
    } finally {
      setBusy(false);
    }
  }

  async function clarify(key: string, answer: string) {
    if (!conversationId) return;
    setBusy(true);
    update(key, { pending: true });
    try {
      const response = await api.post<AskResponse>("clarify", { conversation_id: conversationId, answer });
      update(key, { response, status: response.status ?? undefined, questionId: response.question_id, pending: false });
    } catch (e) {
      update(key, { pending: false, error: e instanceof ApiError ? e.message : "Something went wrong." });
    } finally {
      setBusy(false);
    }
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void ask(text);
    }
  }

  function newConversation() {
    setConversationId(null);
    setTitle(null);
    setTurns([]);
    window.history.replaceState(null, "", "/");
  }

  const examples = EXAMPLES[role ?? ""] ?? [];
  const lastKey = turns.at(-1)?.key;

  return (
    <div className="flex min-h-[calc(100dvh-10rem)] flex-col">
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <h1 className="truncate text-2xl font-semibold tracking-tight">{title ?? "Ask a question"}</h1>
          <p className="text-muted mt-1 text-sm">
            {conversationId ? "Follow-up questions use the earlier questions in this conversation." : "Ask in plain language. Every answer shows how it was calculated."}
          </p>
        </div>
        {(conversationId || turns.length > 0) && (
          <Button variant="secondary" onClick={newConversation}>
            <MessageSquarePlus className="size-4" /> New conversation
          </Button>
        )}
      </div>

      <div className="flex-1 space-y-6">
        {loading && (
          <Card className="space-y-3 p-6">
            <Skeleton className="h-5 w-2/3" />
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-48 w-full" />
          </Card>
        )}
        {loadError && <Alert title="Could not open the conversation">{loadError}</Alert>}

        {!loading && turns.length === 0 && !loadError && (
          <Card className="overflow-hidden">
            <div className="bg-gradient-to-br from-brand-600 to-indigo-500 px-6 py-8 text-white">
              <Sparkles className="size-6 opacity-90" />
              <p className="mt-3 text-lg font-semibold">What would you like to know?</p>
              <p className="mt-1 max-w-xl text-sm text-white/80">
                Answers come from read-only queries on the Northwind data you are allowed to see. Dates are relative to the business date 6 May 2025.
              </p>
            </div>
            {examples.length > 0 && (
              <div className="grid gap-2 p-4 sm:grid-cols-2">
                {examples.map((example) => (
                  <button
                    key={example}
                    onClick={() => void ask(example)}
                    disabled={busy}
                    className="rounded-xl border border-subtle px-4 py-3 text-left text-sm transition hover:border-brand-300 hover:bg-brand-50/60 dark:hover:bg-brand-900/20"
                  >
                    {example}
                  </button>
                ))}
              </div>
            )}
          </Card>
        )}

        {turns.map((turn) => (
          <section key={turn.key} className="animate-fade-up space-y-3">
            <div className="flex justify-end">
              <div className="max-w-[85%] rounded-2xl rounded-br-md bg-brand-600 px-4 py-2.5 text-sm text-white shadow-sm">{turn.question}</div>
            </div>
            <Card className="p-5 sm:p-6">
              {turn.pending && (
                <div className="space-y-3" aria-live="polite">
                  <p className="text-muted text-sm">Checking the question, writing and running a safe query…</p>
                  <Skeleton className="h-4 w-3/4" />
                  <Skeleton className="h-40 w-full" />
                </div>
              )}
              {!turn.pending && turn.error && <Alert title="The question could not be sent">{turn.error}</Alert>}
              {!turn.pending && !turn.error && turn.response && (
                <AnswerCard
                  response={turn.response}
                  questionId={turn.questionId}
                  conversationId={conversationId}
                  isLatest={turn.key === lastKey}
                  busy={busy}
                  onClarify={(answer) => void clarify(turn.key, answer)}
                />
              )}
              {!turn.pending && !turn.error && !turn.response && (
                <div className="flex items-center justify-between gap-3 text-sm">
                  <span className="text-muted">Earlier question in this conversation.</span>
                  <Badge tone={statusTone(turn.status)}>{turn.status?.replace(/_/g, " ").toLowerCase()}</Badge>
                </div>
              )}
            </Card>
          </section>
        ))}
        <div ref={bottom} />
      </div>

      <div className="sticky bottom-0 mt-6 bg-gradient-to-t from-[var(--canvas)] via-[var(--canvas)] to-transparent pb-2 pt-4">
        <form
          onSubmit={(event) => {
            event.preventDefault();
            void ask(text);
          }}
          className="surface flex items-end gap-2 rounded-2xl p-2 shadow-lg focus-within:border-brand-400 focus-within:ring-3 focus-within:ring-brand-500/15"
        >
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value.slice(0, MAX_CHARS))}
            onKeyDown={onKeyDown}
            rows={1}
            placeholder={conversationId ? "Ask a follow-up, e.g. “now only for Germany”" : "e.g. Top 5 products by revenue last quarter"}
            aria-label="Your question"
            className="max-h-40 min-h-11 flex-1 resize-none bg-transparent px-3 py-2.5 text-sm outline-none placeholder:text-slate-400"
          />
          <span className="text-muted hidden pb-3 text-xs sm:block">
            {text.length}/{MAX_CHARS}
          </span>
          <Button type="submit" disabled={!text.trim()} loading={busy} aria-label="Ask" className="size-11 rounded-xl !p-0">
            {!busy && <ArrowUp className="size-5" />}
          </Button>
        </form>
      </div>
    </div>
  );
}
