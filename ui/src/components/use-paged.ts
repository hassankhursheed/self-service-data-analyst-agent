"use client";

import { useEffect, useState } from "react";

import { api, ApiError } from "@/lib/api";
import type { Paged } from "@/lib/types";

interface Result<T> {
  key: string;
  data?: Paged<T>;
  error?: string;
}

/** Load one page of a list endpoint; reloads when the page or the filters change. */
export function usePaged<T>(path: string, query: Record<string, string | undefined> = {}, pageSize = 20) {
  const queryKey = JSON.stringify(query);
  // The page belongs to one set of filters: new filters start again at page 1.
  const [pageState, setPageState] = useState({ queryKey, page: 1 });
  const page = pageState.queryKey === queryKey ? pageState.page : 1;
  const [nonce, setNonce] = useState(0);
  const [result, setResult] = useState<Result<T> | null>(null);
  const [lastData, setLastData] = useState<Paged<T> | null>(null);
  const key = `${path}|${page}|${pageSize}|${queryKey}|${nonce}`;

  useEffect(() => {
    let cancelled = false;
    const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
    for (const [name, value] of Object.entries(JSON.parse(queryKey) as Record<string, string | undefined>)) {
      if (value) params.set(name, value);
    }
    api
      .get<Paged<T>>(`${path}?${params}`)
      .then((data) => {
        if (cancelled) return;
        setResult({ key, data });
        setLastData(data);
      })
      .catch((e: unknown) => {
        if (!cancelled) setResult({ key, error: e instanceof ApiError ? e.message : "Could not load the list." });
      });
    return () => {
      cancelled = true;
    };
  }, [key, path, page, pageSize, queryKey]);

  const loading = result?.key !== key;
  return {
    data: loading ? lastData : (result?.data ?? null),
    error: loading ? null : (result?.error ?? null),
    loading,
    page,
    setPage: (next: number) => setPageState({ queryKey, page: next }),
    pageSize,
    reload: () => setNonce((n) => n + 1),
  };
}
