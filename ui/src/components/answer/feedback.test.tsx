import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { FeedbackBar } from "./feedback";

function mockFetch() {
  return vi
    .spyOn(globalThis, "fetch")
    .mockResolvedValue(new Response(JSON.stringify({ correlation_id: "x", feedback_id: 1, rating: "helpful" }), { status: 200 }));
}

describe("FeedbackBar", () => {
  it("sends 'helpful' at once through the UI's own proxy", async () => {
    const fetchSpy = mockFetch();
    render(<FeedbackBar questionId="q-1" />);
    await userEvent.click(screen.getByRole("button", { name: /^helpful/i }));
    expect(await screen.findByTestId("feedback-saved")).toBeInTheDocument();
    const [url, init] = fetchSpy.mock.calls[0]!;
    expect(url).toBe("/api/proxy/feedback");
    expect(JSON.parse(String(init?.body))).toEqual({ question_id: "q-1", rating: "helpful", comment: null });
  });

  it("asks for an optional comment for 'not helpful'", async () => {
    const fetchSpy = mockFetch();
    render(<FeedbackBar questionId="q-1" />);
    await userEvent.click(screen.getByRole("button", { name: /not helpful/i }));
    await userEvent.type(screen.getByLabelText("Feedback comment"), "Missing the discount.");
    await userEvent.click(screen.getByRole("button", { name: /send feedback/i }));
    await screen.findByTestId("feedback-saved");
    expect(JSON.parse(String(fetchSpy.mock.calls[0]![1]?.body))).toEqual({
      question_id: "q-1",
      rating: "not_helpful",
      comment: "Missing the discount.",
    });
  });
});
