import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AlertsList } from "./recent-alerts";

describe("AlertsList", () => {
  it("lists alerts with their type and message, and marks the ones sent to Slack", () => {
    render(
      <AlertsList
        items={[
          {
            id: 2,
            alert_type: "failed_logins",
            metric_value: "12",
            threshold: "10",
            message: "12 failed logins in the last 60 minutes (threshold 10).",
            channel: "slack",
            sent_at: "2026-11-08T10:00:01Z",
            created_at: "2026-11-08T10:00:00Z",
          },
        ]}
      />,
    );
    expect(screen.getByTestId("alerts-list")).toHaveTextContent("12 failed logins");
    expect(screen.getByLabelText("Sent to Slack")).toBeInTheDocument();
  });

  it("says when there are no alerts", () => {
    render(<AlertsList items={[]} />);
    expect(screen.getByText(/No alerts/)).toBeInTheDocument();
  });
});
