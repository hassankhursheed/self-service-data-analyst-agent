import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { answered, blocked } from "@/test/fixtures";

import { AnswerCard } from "./answer-card";
import { ChartView } from "./chart-view";
import { Clarification } from "./clarification";

const card = (response = answered) => (
  <AnswerCard response={response} questionId="q1" conversationId="c1" isLatest busy={false} onClarify={() => {}} />
);

describe("ChartView", () => {
  it("draws the component the chart spec asks for", () => {
    const base = { x: "month", y: ["revenue"], data: [{ month: "2024-01", revenue: 10 }], title: null, reason: "r" };
    const { rerender, container } = render(<ChartView spec={{ ...base, type: "line" }} />);
    expect(screen.getByTestId("chart-line")).toBeInTheDocument();
    rerender(<ChartView spec={{ ...base, type: "bar" }} />);
    expect(screen.getByTestId("chart-bar")).toBeInTheDocument();
    rerender(<ChartView spec={{ ...base, type: "metric_card" }} />);
    expect(screen.getByTestId("chart-metric_card")).toHaveTextContent("10");
    rerender(<ChartView spec={{ ...base, type: "none" }} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("AnswerCard", () => {
  it("shows the answer with its date range, row count, assumptions, SQL and feedback", async () => {
    render(card());
    expect(screen.getByText(answered.answer!)).toBeInTheDocument();
    expect(screen.getByText("Last quarter = 1 Jan to 31 Mar 2025")).toBeInTheDocument();
    expect(screen.getAllByText("1 row").length).toBeGreaterThan(0);
    expect(screen.getByText("Revenue includes discounts.")).toBeInTheDocument();
    expect(screen.getByTestId("result-table")).toHaveTextContent("81,234.5");
    expect(screen.getByTestId("download-csv")).toHaveAttribute("href", "/api/proxy/conversations/c1/table.csv");
    expect(screen.getByText("Sums order revenue for European customers.")).toBeInTheDocument();
    await userEvent.click(screen.getByText("How this was calculated"));
    expect(screen.getByText(answered.sql.text!)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /not helpful/i })).toBeInTheDocument();
  });

  it("shows the low-confidence label", () => {
    render(card({ ...answered, low_confidence: true, low_confidence_label: "Low confidence: please check" }));
    expect(screen.getByText("Low confidence: please check")).toBeInTheDocument();
  });

  it.each([
    ["BLOCKED", "This request was blocked"],
    ["REJECTED", "This question can't be answered here"],
    ["FAILED", "Something went wrong answering this"],
  ] as const)("shows a friendly message for %s and no data", (status, title) => {
    render(card({ ...blocked, status, block: status === "FAILED" ? null : blocked.block }));
    expect(screen.getByTestId(`outcome-${status}`)).toHaveTextContent(title);
    expect(screen.getByText(/only read-only questions are allowed/i)).toBeInTheDocument();
    expect(screen.queryByTestId("result-table")).not.toBeInTheDocument();
    expect(screen.queryByText("How this was calculated")).not.toBeInTheDocument();
  });
});

describe("Clarification", () => {
  it("sends the chosen option or a typed answer", async () => {
    const onAnswer = vi.fn();
    render(<Clarification question="By revenue or by orders?" options={["By revenue", "By orders"]} busy={false} onAnswer={onAnswer} />);
    await userEvent.click(screen.getByRole("button", { name: "By orders" }));
    expect(onAnswer).toHaveBeenCalledWith("By orders");
    await userEvent.type(screen.getByLabelText("Your answer"), "By revenue in 2024");
    await userEvent.click(screen.getByLabelText("Send answer"));
    expect(onAnswer).toHaveBeenLastCalledWith("By revenue in 2024");
  });
});
