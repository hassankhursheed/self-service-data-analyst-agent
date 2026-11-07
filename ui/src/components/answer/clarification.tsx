"use client";

import { HelpCircle, Send } from "lucide-react";
import { useState } from "react";

import { Button, Input } from "../ui";

/** The clarifying question, its options as buttons, and a free-text reply. */
export function Clarification({
  question,
  options,
  busy,
  onAnswer,
}: {
  question: string;
  options: string[];
  busy: boolean;
  onAnswer: (answer: string) => void;
}) {
  const [text, setText] = useState("");
  return (
    <div className="space-y-3 rounded-xl bg-brand-50/70 p-4 ring-1 ring-brand-100 dark:bg-brand-900/20 dark:ring-brand-900" data-testid="clarification">
      <p className="flex gap-2 text-sm font-medium">
        <HelpCircle className="mt-0.5 size-4 shrink-0 text-brand-600 dark:text-brand-400" />
        {question}
      </p>
      {options.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {options.map((option) => (
            <Button key={option} variant="secondary" size="sm" disabled={busy} onClick={() => onAnswer(option)}>
              {option}
            </Button>
          ))}
        </div>
      )}
      <form
        className="flex gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          if (text.trim()) onAnswer(text.trim());
        }}
      >
        <Input value={text} onChange={(e) => setText(e.target.value)} placeholder="Or type your own answer" maxLength={1000} aria-label="Your answer" />
        <Button type="submit" variant="secondary" disabled={busy || !text.trim()} aria-label="Send answer">
          <Send className="size-4" />
        </Button>
      </form>
    </div>
  );
}
