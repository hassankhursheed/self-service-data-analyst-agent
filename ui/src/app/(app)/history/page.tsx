import { PageHeader } from "@/components/app-shell";
import { HistoryList } from "@/components/history-list";

export default function HistoryPage() {
  return (
    <>
      <PageHeader title="History" description="Your previous conversations. Open one to see its answers and continue asking." />
      <HistoryList />
    </>
  );
}
