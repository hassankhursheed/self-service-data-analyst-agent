"use client";

import { ChevronRight, MessagesSquare } from "lucide-react";
import Link from "next/link";

import { formatDateTime } from "@/lib/format";
import type { ConversationSummary } from "@/lib/types";

import { Pager } from "./pager";
import { Alert, Badge, Button, Card, EmptyState, Skeleton } from "./ui";
import { usePaged } from "./use-paged";

export function HistoryList() {
  const { data, error, loading, page, setPage, pageSize } = usePaged<ConversationSummary>("conversations");
  if (error) return <Alert title="Could not load your history">{error}</Alert>;
  return (
    <Card className="overflow-hidden">
      {loading && !data && (
        <div className="space-y-3 p-5">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-12 w-full" />
          ))}
        </div>
      )}
      {data && data.items.length === 0 && (
        <EmptyState icon={<MessagesSquare className="size-6" />} title="No conversations yet">
          <p>Questions you ask are saved here so you can come back to them.</p>
          <Link href="/" className="mt-4 inline-block">
            <Button>Ask your first question</Button>
          </Link>
        </EmptyState>
      )}
      {data && data.items.length > 0 && (
        <ul className="divide-y divide-[var(--border)]">
          {data.items.map((conversation) => (
            <li key={conversation.id}>
              <Link href={`/?c=${conversation.id}`} className="flex items-center gap-3 px-4 py-4 transition hover:bg-muted sm:gap-4 sm:px-5">
                <div className="rounded-xl bg-brand-50 p-2 text-brand-600 dark:bg-brand-900/40 dark:text-brand-200">
                  <MessagesSquare className="size-4" />
                </div>
                <div className="min-w-0 flex-1">
                  <p className="line-clamp-2 font-medium sm:truncate">{conversation.title}</p>
                  <p className="text-muted text-xs">
                    Last activity {formatDateTime(conversation.updated_at)}
                    <span className="sm:hidden">
                      {" · "}
                      {conversation.question_count} {conversation.question_count === 1 ? "question" : "questions"}
                    </span>
                  </p>
                </div>
                <span className="hidden sm:block">
                  <Badge>
                    {conversation.question_count} {conversation.question_count === 1 ? "question" : "questions"}
                  </Badge>
                </span>
                <ChevronRight className="text-muted size-4" />
              </Link>
            </li>
          ))}
        </ul>
      )}
      {data && <Pager page={page} pageSize={pageSize} total={data.total} onPage={setPage} />}
    </Card>
  );
}
