import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { AnswerItem, ChartSpec } from "@/lib/types";
import { answered } from "@/test/fixtures";

import { AnswerCard } from "./answer-card";
import { RankedResults } from "./ranked-results";

const items: AnswerItem[] = [
  { label: "Thüringer Rostbratwurst", value: 27537.13, detail: null },
  { label: "Côte de Blaye", value: 22002.25, detail: "Beverages" },
  { label: "Raclette Courdavault", value: 21705.75, detail: null },
];

const bar: ChartSpec = {
  type: "bar",
  x: "product_name",
  y: ["revenue"],
  data: items.map((i) => ({ product_name: i.label, revenue: i.value })),
  title: null,
  reason: "comparison across categories",
};

const card = (withItems: AnswerItem[]) => (
  <AnswerCard
    response={{ ...answered, answer: "Here are the 3 products with the highest revenue in 2024.", chart: bar, items: withItems }}
    questionId="q1"
    conversationId="c1"
    isLatest
    busy={false}
    onClarify={() => {}}
  />
);

describe("ranked results (structured answer items)", () => {
  it("lists every item with its rank, value and detail", () => {
    render(<RankedResults items={items} valueLabel="revenue" />);
    const rows = screen.getAllByTestId("ranked-item");
    expect(rows).toHaveLength(3);
    expect(within(rows[0]!).getByLabelText("Rank 1")).toBeInTheDocument();
    expect(rows[0]).toHaveTextContent("Thüringer Rostbratwurst");
    expect(rows[0]).toHaveTextContent("27,537.13");
    expect(rows[1]).toHaveTextContent("Beverages");
    expect(screen.getByText("Revenue")).toBeInTheDocument();
  });

  it("shows the summary text first, then the list, instead of a bar chart", () => {
    render(card(items));
    const summary = screen.getByText(/Here are the 3 products/);
    const list = screen.getByTestId("ranked-results");
    expect(summary.compareDocumentPosition(list) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.queryByTestId("chart-bar")).not.toBeInTheDocument();
  });

  it("keeps the chart when there are no items", () => {
    render(card([]));
    expect(screen.queryByTestId("ranked-results")).not.toBeInTheDocument();
    expect(screen.getByTestId("chart-bar")).toBeInTheDocument();
  });
});
