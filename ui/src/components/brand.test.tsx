import { act, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { answered } from "@/test/fixtures";
import { adminUser, salesUser } from "@/test/fixtures";
import { resolveTheme } from "@/lib/theme";

import { AgentProgress, AGENT_STEPS } from "./answer/agent-progress";
import { AnswerCard } from "./answer/answer-card";
import { ScopeChip } from "./app-shell";
import { LogoMark, Wordmark } from "./logo";

vi.mock("next/navigation", () => ({ usePathname: () => "/" }));

afterEach(() => {
  vi.useRealTimers();
});

describe("AskData branding", () => {
  it("shows the AskData name and an accessible logo", () => {
    render(<Wordmark />);
    expect(screen.getByRole("img", { name: "AskData logo" })).toBeInTheDocument();
    expect(screen.getByText("Data")).toBeInTheDocument();
    render(<LogoMark size={16} />);
  });

  it("resolves the theme choice", () => {
    expect(resolveTheme("system", true)).toBe("dark");
    expect(resolveTheme("system", false)).toBe("light");
    expect(resolveTheme("light", true)).toBe("light");
  });
});

describe("scope chip", () => {
  it("says what the answers are limited to", () => {
    const { unmount } = render(<ScopeChip user={salesUser} />);
    expect(screen.getByTestId("scope-chip")).toHaveTextContent("Europe · read-only");
    unmount();
    render(<ScopeChip user={adminUser} />);
    expect(screen.getByTestId("scope-chip")).toHaveTextContent("Admin · no business data");
  });
});

describe("verified answers", () => {
  const card = (verified: boolean, low = false) => (
    <AnswerCard
      response={{ ...answered, verified, low_confidence: low }}
      questionId="q1"
      conversationId="c1"
      isLatest
      busy={false}
      onClarify={() => {}}
    />
  );

  it("shows the Verified badge only for verified answers", () => {
    const { unmount } = render(card(true));
    expect(screen.getByText("Verified against the data")).toBeInTheDocument();
    unmount();
    render(card(false, true));
    expect(screen.queryByText("Verified against the data")).not.toBeInTheDocument();
    expect(screen.getByText(/Low confidence/)).toBeInTheDocument();
  });
});

describe("agent progress", () => {
  it("advances through the steps and keeps the last one active", () => {
    vi.useFakeTimers();
    render(<AgentProgress startedAt={Date.now()} />);
    expect(screen.getByText(AGENT_STEPS[0])).toHaveClass("font-medium");
    act(() => {
      vi.advanceTimersByTime(20000);
    });
    expect(screen.getByText(AGENT_STEPS[4])).toHaveClass("font-medium");
    expect(screen.getByText(/Still working/)).toBeInTheDocument();
  });
});
