import { PageHeader } from "@/components/app-shell";
import { ReviewBoard } from "@/components/admin/review-board";

export default function ReviewPage() {
  return (
    <>
      <PageHeader title="Review" description="Answers rated not helpful, blocked queries and failures. Verify or correct queries for the library, or turn feedback into evaluation cases." />
      <ReviewBoard />
    </>
  );
}
