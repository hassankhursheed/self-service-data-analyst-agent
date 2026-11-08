import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ChartSpec } from "@/lib/types";

import { ChartView } from "./chart-view";

const bar: ChartSpec = {
  type: "bar",
  x: "product_name",
  y: ["revenue"],
  data: [
    { product_name: "Thüringer Rostbratwurst", revenue: 27537.13 },
    { product_name: "Côte de Blaye", revenue: 22002.25 },
  ],
  title: null,
  reason: "comparison across categories",
};

function screenWidth(narrow: boolean) {
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: narrow && query.includes("max-width"),
    media: query,
    addEventListener: () => {},
    removeEventListener: () => {},
  }));
}

afterEach(() => vi.unstubAllGlobals());

describe("charts on phones", () => {
  it("draws bars sideways on narrow screens so every label fits", () => {
    screenWidth(true);
    render(<ChartView spec={bar} />);
    expect(screen.getByTestId("chart-bar")).toHaveAttribute("data-layout", "horizontal");
  });

  it("keeps vertical bars on wider screens", () => {
    screenWidth(false);
    render(<ChartView spec={bar} />);
    expect(screen.getByTestId("chart-bar")).not.toHaveAttribute("data-layout");
  });
});
