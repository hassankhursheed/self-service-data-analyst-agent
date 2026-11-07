import { Activity } from "lucide-react";

import { PageHeader } from "@/components/app-shell";
import { ComingSoon } from "@/components/coming-soon";

export default function MonitoringPage() {
  return (
    <>
      <PageHeader title="Monitoring" description="The operations view of the agent (brief §26)." />
      <ComingSoon
        icon={<Activity className="size-6" />}
        step="Steps 20–22"
        items={[
          "Questions today by role, and outcomes (answered, blocked, rejected, failed)",
          "Blocked queries by reason, repair attempts and success rate",
          "Latency (average and p95), tokens and cost today",
          "Feedback counts, failed logins and the latest evaluation run",
        ]}
      />
    </>
  );
}
