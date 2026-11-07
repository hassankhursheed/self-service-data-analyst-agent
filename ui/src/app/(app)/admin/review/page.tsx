import { PageHeader } from "@/components/app-shell";
import { ReviewBoard } from "@/components/admin/review-board";

export default function ReviewPage() {
  return (
    <>
      <PageHeader title="Review" description="Blocked queries and failures. Verifying and correcting queries arrives in Step 20." />
      <ReviewBoard />
    </>
  );
}
