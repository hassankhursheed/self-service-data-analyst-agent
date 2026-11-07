import { ShieldOff } from "lucide-react";
import { redirect } from "next/navigation";

import { AskWorkspace } from "@/components/ask-workspace";
import { Card, EmptyState } from "@/components/ui";
import { getCurrentUser } from "@/lib/server/api";

export default async function AskPage({ searchParams }: { searchParams: Promise<{ c?: string }> }) {
  const user = await getCurrentUser();
  if (!user) redirect("/login");
  // Admins manage the system; business questions are off for them (brief §8).
  if (user.role === "admin") redirect("/admin/users");
  if (!user.role) {
    return (
      <Card>
        <EmptyState icon={<ShieldOff className="size-6" />} title="No data access yet">
          Your account does not have a role, so it cannot query any data. Ask an administrator to assign you a role.
        </EmptyState>
      </Card>
    );
  }
  const { c } = await searchParams;
  const conversationId = c && /^[0-9a-f-]{36}$/.test(c) ? c : null;
  return <AskWorkspace key={conversationId ?? "new"} role={user.role} conversationId={conversationId} />;
}
