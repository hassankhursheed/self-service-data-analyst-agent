import { FlaskConical } from "lucide-react";

import { PageHeader } from "@/components/app-shell";
import { ComingSoon } from "@/components/coming-soon";

export default function EvaluationPage() {
  return (
    <>
      <PageHeader title="Evaluation" description="Run the evaluation set and compare runs." />
      <ComingSoon
        icon={<FlaskConical className="size-6" />}
        step="Steps 20–22"
        items={[
          "Start an evaluation run, with or without verified examples",
          "Compare runs: execution accuracy, unsafe-blocked rate, access leaks, latency, cost",
          "See failing cases with the expected and the produced result",
        ]}
      />
    </>
  );
}
