import { PageHeader } from "@/components/app-shell";
import { EvaluationBoard } from "@/components/admin/evaluation-board";

export default function EvaluationPage() {
  return (
    <>
      <PageHeader title="Evaluation" description="Run the 60-case evaluation set, compare experiments and inspect failing cases (brief §24)." />
      <EvaluationBoard />
    </>
  );
}
