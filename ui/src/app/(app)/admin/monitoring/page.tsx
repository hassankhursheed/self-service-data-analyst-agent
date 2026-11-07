import { PageHeader } from "@/components/app-shell";
import { MonitoringBoard } from "@/components/admin/monitoring-board";

export default function MonitoringPage() {
  return (
    <>
      <PageHeader title="Monitoring" description="Operational health of the agent: outcomes, safety, quality, speed and cost (brief §26)." />
      <MonitoringBoard />
    </>
  );
}
