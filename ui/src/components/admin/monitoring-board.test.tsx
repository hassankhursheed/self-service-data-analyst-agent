import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { MonitoringView, type Metrics } from "./monitoring-board";

const metrics: Metrics = {
  correlation_id: "c",
  period_from: "2026-11-01",
  period_to: "2026-11-07",
  time_zone: "UTC",
  questions: 10,
  questions_by_role: { sales_manager: 6, finance_analyst: 4 },
  outcomes: { answered: 6, blocked: 2, rejected: 0, failed: 2, awaiting_clarification: 0, in_progress: 0 },
  blocked_by_reason: { WRITE_REQUEST: 2 },
  repair_attempts: 3,
  repaired_runs: 2,
  repair_success_rate: 0.5,
  clarifications_asked: 1,
  runs: 11,
  latency_avg_ms: 2400,
  latency_p95_ms: 7150,
  input_tokens: 1000,
  output_tokens: 250,
  cost_usd: "0.0125",
  feedback: { helpful: 3, not_helpful: 1 },
  failed_logins: 2,
  latest_eval_run: null,
  daily: [{ date: "2026-11-07", questions: 10, answered: 6, blocked: 2, rejected: 0, failed: 2, cost_usd: "0.0125" }],
  node_latency: [{ node: "N-06", label: "SQL generation", steps: 11, avg_ms: 2100, p95_ms: 4800 }],
};

describe("MonitoringView", () => {
  it("shows the operational metrics as rates and counts", () => {
    render(<MonitoringView metrics={metrics} />);
    expect(screen.getByTestId("stat-Questions")).toHaveTextContent("10");
    expect(screen.getByTestId("stat-Answered")).toHaveTextContent("60.0%");
    expect(screen.getByTestId("stat-Failure rate")).toHaveTextContent("20.0%");
    expect(screen.getByTestId("stat-Latency p95")).toHaveTextContent("7.15 s");
    expect(screen.getByTestId("stat-Estimated cost")).toHaveTextContent("$0.0125");
    expect(screen.getByTestId("stat-Repair success")).toHaveTextContent("50.0%");
    expect(screen.getByTestId("stat-Helpful ratings")).toHaveTextContent("75.0%");
    expect(screen.getByTestId("stat-Failed logins")).toHaveTextContent("2");
    expect(screen.getByText("Sales manager")).toBeInTheDocument();
    expect(screen.getByText("Write request")).toBeInTheDocument();
    expect(screen.getByText(/No evaluation run yet/)).toBeInTheDocument();
    expect(screen.getByTestId("node-latency")).toHaveTextContent("SQL generation");
    expect(screen.getByTestId("node-latency")).toHaveTextContent("4.80 s");
  });
});
