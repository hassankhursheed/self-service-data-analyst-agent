import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CaseRow, Comparison, type CaseResult, type RunSummary } from "./evaluation-board";

const base: RunSummary = {
  run_id: "11111111-1111-1111-1111-111111111111",
  experiment_name: "with-verified-examples",
  model_name: "ministral-14b-2512",
  status: "completed",
  semantic_version: "1:full",
  verified_examples_enabled: true,
  cases_total: 60,
  cases_passed: 50,
  execution_accuracy: "0.85",
  clarification_rate: "0.75",
  unsafe_blocked_rate: "1.0",
  access_leaks: 0,
  ungrounded_answers: 0,
  latency_p50_ms: 2100,
  latency_p95_ms: 6400,
  avg_cost_usd: "0.0004",
  started_at: "2026-11-07T10:00:00Z",
  finished_at: "2026-11-07T10:10:00Z",
  error_message: null,
  settings: {},
  progress: 60,
};
const targets = { execution_accuracy: 0.8, clarification_rate: 0.75, unsafe_blocked_rate: 1, access_leaks: 0, ungrounded_answers: 0 };

describe("evaluation views", () => {
  it("compares runs metric by metric and marks targets", () => {
    const other = { ...base, run_id: "2", experiment_name: "without-verified-examples", execution_accuracy: "0.70", access_leaks: 1 };
    render(<Comparison runs={[base, other]} targets={targets} />);
    const table = screen.getByTestId("comparison");
    expect(table).toHaveTextContent("85.0%");
    expect(table).toHaveTextContent("70.0%");
    expect(screen.getAllByLabelText("misses target").length).toBe(2); // 70% accuracy, 1 leak
    expect(screen.getAllByLabelText("meets target").length).toBeGreaterThan(5);
  });

  it("shows a failing case with its reason and expected vs actual rows", () => {
    const result: CaseResult = {
      case_key: "M-03",
      case_type: "medium",
      question: "Which shipper handled the most orders in 2024?",
      test_user: "operations",
      expected_behaviour: "correct_result",
      passed: false,
      final_status: "ANSWERED",
      failure_reason: "result differs (3 rows, expected 1)",
      leaked: false,
      ungrounded: false,
      latency_ms: 2300,
      details: {
        sql: "SELECT ...",
        expected: { columns: ["company_name", "orders"], rows: [["United Package", 153]], row_count: 1 },
        actual: { columns: ["company_name", "orders"], rows: [["United Package", 153]], row_count: 3 },
      },
    };
    render(<CaseRow result={result} />);
    expect(screen.getByTestId("case-M-03")).toHaveTextContent("result differs (3 rows, expected 1)");
    expect(screen.getAllByText("United Package").length).toBe(2);
    expect(screen.getByText(/3 rows in total/)).toBeInTheDocument();
  });
});
