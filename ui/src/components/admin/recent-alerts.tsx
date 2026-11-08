"use client";

import { BellRing, Send } from "lucide-react";
import { useEffect, useState } from "react";

import { api, ApiError } from "@/lib/api";
import { formatDateTime, humanize } from "@/lib/format";

import { Card } from "../ui";

export interface AlertItem {
  id: number;
  alert_type: string;
  metric_value: string;
  threshold: string;
  message: string;
  channel: string;
  sent_at: string | null;
  created_at: string;
}

/** Alerts raised when a monitoring number passes its threshold (newest first). */
export function AlertsList({ items }: { items: AlertItem[] }) {
  return (
    <Card className="p-5">
      <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold">
        <BellRing className="size-4 text-amber-600" aria-hidden />
        Recent alerts
      </h3>
      {items.length === 0 ? (
        <p className="text-muted text-sm">No alerts. Thresholds are set in config/app.yaml (alerts).</p>
      ) : (
        <ul className="divide-y divide-[var(--border)]" data-testid="alerts-list">
          {items.map((alert) => (
            <li key={alert.id} className="flex flex-wrap items-start justify-between gap-2 py-2 text-sm">
              <div>
                <span className="mr-2 rounded-md bg-amber-100 px-1.5 py-0.5 text-xs font-medium text-amber-800 dark:bg-amber-900/40 dark:text-amber-200">
                  {humanize(alert.alert_type)}
                </span>
                {alert.message}
              </div>
              <span className="text-muted inline-flex items-center gap-1 text-xs">
                {alert.sent_at && <Send className="size-3" aria-label="Sent to Slack" />}
                {formatDateTime(alert.created_at)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

export function RecentAlerts({ refreshKey }: { refreshKey: number }) {
  const [items, setItems] = useState<AlertItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    api
      .get<{ items: AlertItem[] }>("admin/alerts?limit=10")
      .then((body) => !cancelled && setItems(body.items))
      .catch((e: unknown) => !cancelled && setError(e instanceof ApiError ? e.message : "Could not load the alerts."));
    return () => {
      cancelled = true;
    };
  }, [refreshKey]);
  if (error) return <p className="text-sm text-rose-600">{error}</p>;
  return items ? <AlertsList items={items} /> : null;
}
