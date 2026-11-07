import type { ReactNode } from "react";

import { Badge, Card } from "./ui";

export function ComingSoon({ icon, step, items }: { icon: ReactNode; step: string; items: string[] }) {
  return (
    <Card className="overflow-hidden">
      <div className="flex flex-col gap-6 p-6 sm:flex-row sm:items-start">
        <div className="rounded-2xl bg-brand-50 p-3 text-brand-600 dark:bg-brand-900/40 dark:text-brand-200">{icon}</div>
        <div className="space-y-3">
          <Badge tone="amber">Arrives in {step}</Badge>
          <p className="text-muted text-sm">This screen is planned and its API contract is ready. It will show:</p>
          <ul className="list-disc space-y-1 pl-5 text-sm">
            {items.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </div>
      </div>
    </Card>
  );
}
