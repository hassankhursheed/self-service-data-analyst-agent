"use client";

import { ChevronLeft, ChevronRight } from "lucide-react";

import { Button } from "./ui";

export function Pager({ page, pageSize, total, onPage }: { page: number; pageSize: number; total: number; onPage: (page: number) => void }) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  if (total <= pageSize) return null;
  return (
    <div className="text-muted flex items-center justify-end gap-2 px-4 py-3 text-xs">
      <span>
        Page {page} of {pages} · {total} total
      </span>
      <Button variant="secondary" size="sm" aria-label="Previous page" disabled={page <= 1} onClick={() => onPage(page - 1)}>
        <ChevronLeft className="size-3.5" />
      </Button>
      <Button variant="secondary" size="sm" aria-label="Next page" disabled={page >= pages} onClick={() => onPage(page + 1)}>
        <ChevronRight className="size-3.5" />
      </Button>
    </div>
  );
}
