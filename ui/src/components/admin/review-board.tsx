"use client";

import { RotateCw, ShieldAlert, TriangleAlert } from "lucide-react";
import { useState } from "react";

import { api, ApiError } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import type { BlockedItem, ErrorItem } from "@/lib/types";

import { Pager } from "../pager";
import { Alert, Badge, Button, Card, EmptyState, Skeleton } from "../ui";
import { usePaged } from "../use-paged";

function Blocked() {
  const { data, error, loading, page, setPage, pageSize } = usePaged<BlockedItem>("admin/blocked", {}, 10);
  if (error) return <Alert>{error}</Alert>;
  if (loading && !data) return <Skeleton className="m-5 h-24" />;
  if (!data?.items.length) return <EmptyState icon={<ShieldAlert className="size-6" />} title="Nothing blocked">Blocked questions and queries appear here.</EmptyState>;
  return (
    <>
      <ul className="divide-y divide-[var(--border)]">
        {data.items.map((item) => (
          <li key={item.id} className="space-y-1.5 px-5 py-4">
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone="red">{item.reason_code.replace(/_/g, " ").toLowerCase()}</Badge>
              <Badge>{item.stage.replace(/_/g, " ")}</Badge>
              <span className="text-muted text-xs">
                {item.username ?? "unknown"} · {item.role ?? "no role"} · {formatDateTime(item.created_at)}
              </span>
            </div>
            {item.question && <p className="text-sm font-medium">“{item.question}”</p>}
            <p className="text-muted text-sm">{item.reason_text}</p>
            {item.sql_text && <pre className="overflow-x-auto rounded-lg bg-slate-950 p-3 font-mono text-xs text-slate-100">{item.sql_text}</pre>}
          </li>
        ))}
      </ul>
      <Pager page={page} pageSize={pageSize} total={data.total} onPage={setPage} />
    </>
  );
}

function Errors() {
  const { data, error, loading, page, setPage, pageSize, reload } = usePaged<ErrorItem>("admin/errors", {}, 10);
  const [busy, setBusy] = useState<number | null>(null);
  const [notice, setNotice] = useState<{ tone: "green" | "red"; text: string } | null>(null);

  async function rerun(item: ErrorItem) {
    setBusy(item.id);
    setNotice(null);
    try {
      const result = await api.post<{ status: string | null }>(`admin/errors/${item.id}/rerun`);
      setNotice({ tone: "green", text: `Re-run as ${item.username ?? "the original user"} finished: ${result.status ?? "unknown"}.` });
      void reload();
    } catch (e) {
      setNotice({ tone: "red", text: e instanceof ApiError ? e.message : "Could not re-run." });
    } finally {
      setBusy(null);
    }
  }

  if (error) return <Alert>{error}</Alert>;
  if (loading && !data) return <Skeleton className="m-5 h-24" />;
  return (
    <>
      {notice && (
        <div className="px-5 pt-4">
          <Alert tone={notice.tone}>{notice.text}</Alert>
        </div>
      )}
      {!data?.items.length ? (
        <EmptyState icon={<TriangleAlert className="size-6" />} title="No failures">Errors recorded by the agent appear here.</EmptyState>
      ) : (
        <ul className="divide-y divide-[var(--border)]">
          {data.items.map((item) => (
            <li key={item.id} className="flex flex-wrap items-start gap-4 px-5 py-4">
              <div className="min-w-0 flex-1 space-y-1.5">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge tone={item.status === "open" ? "red" : "neutral"}>{item.status}</Badge>
                  <Badge>{item.error_type}</Badge>
                  {item.node_name && <Badge tone="brand">{item.node_name}</Badge>}
                  <span className="text-muted text-xs">
                    {item.username ?? "unknown"} · {formatDateTime(item.created_at)}
                  </span>
                </div>
                <p className="text-muted break-words text-sm">{item.error_message}</p>
                <p className="text-muted font-mono text-[11px]">ref {item.correlation_id.slice(0, 8)}</p>
              </div>
              <Button variant="secondary" size="sm" disabled={item.status !== "open"} loading={busy === item.id} onClick={() => void rerun(item)}>
                <RotateCw className="size-3.5" /> Re-run
              </Button>
            </li>
          ))}
        </ul>
      )}
      {data && <Pager page={page} pageSize={pageSize} total={data.total} onPage={setPage} />}
    </>
  );
}

export function ReviewBoard() {
  const [tab, setTab] = useState<"blocked" | "errors">("blocked");
  return (
    <div className="space-y-4">
      <div className="surface inline-flex rounded-xl p-1" role="tablist">
        {(["blocked", "errors"] as const).map((name) => (
          <button
            key={name}
            role="tab"
            aria-selected={tab === name}
            onClick={() => setTab(name)}
            className={`rounded-lg px-4 py-1.5 text-sm font-medium transition ${tab === name ? "bg-brand-600 text-white shadow-sm" : "text-muted hover:text-[var(--text)]"}`}
          >
            {name === "blocked" ? "Blocked queries" : "Failures"}
          </button>
        ))}
      </div>
      <Card className="overflow-hidden">{tab === "blocked" ? <Blocked /> : <Errors />}</Card>
      <Card className="p-5">
        <p className="text-sm font-medium">Not-helpful answers and verified queries</p>
        <p className="text-muted mt-1 text-sm">Reviewing answers rated “not helpful”, verifying or correcting their SQL and turning them into evaluation cases arrive in Step 20.</p>
      </Card>
    </div>
  );
}
