"use client";

import { CheckCircle2, ThumbsDown, ThumbsUp } from "lucide-react";
import { useState } from "react";

import { api, ApiError } from "@/lib/api";

import { Button, inputClass } from "../ui";

type Rating = "helpful" | "not_helpful";

/** Helpful / Not helpful, with an optional comment (always offered for "not helpful"). */
export function FeedbackBar({ questionId }: { questionId: string }) {
  const [rating, setRating] = useState<Rating | null>(null);
  const [comment, setComment] = useState("");
  const [saved, setSaved] = useState<Rating | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function send(chosen: Rating, text: string) {
    setBusy(true);
    setError(null);
    try {
      await api.post("feedback", { question_id: questionId, rating: chosen, comment: text.trim() || null });
      setSaved(chosen);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not save your feedback.");
    } finally {
      setBusy(false);
    }
  }

  if (saved) {
    return (
      <p className="inline-flex items-center gap-2 text-sm text-emerald-700 dark:text-emerald-400" data-testid="feedback-saved">
        <CheckCircle2 className="size-4" /> Thanks for your feedback.
        <button className="text-muted underline-offset-2 hover:underline" onClick={() => { setSaved(null); setRating(saved); }}>
          Change
        </button>
      </p>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-muted w-full text-sm sm:w-auto">Was this answer helpful?</span>
        <Button variant={rating === "helpful" ? "primary" : "secondary"} size="sm" className="min-h-9" disabled={busy} onClick={() => { setRating("helpful"); void send("helpful", comment); }}>
          <ThumbsUp className="size-3.5" /> Helpful
        </Button>
        <Button variant={rating === "not_helpful" ? "primary" : "secondary"} size="sm" className="min-h-9" disabled={busy} onClick={() => setRating("not_helpful")}>
          <ThumbsDown className="size-3.5" /> Not helpful
        </Button>
      </div>
      {rating === "not_helpful" && (
        <form
          className="space-y-2"
          onSubmit={(event) => {
            event.preventDefault();
            void send("not_helpful", comment);
          }}
        >
          <textarea
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            maxLength={1000}
            rows={2}
            placeholder="What was wrong or missing? (optional)"
            aria-label="Feedback comment"
            className={inputClass}
          />
          <Button type="submit" size="sm" loading={busy}>
            Send feedback
          </Button>
        </form>
      )}
      {error && <p className="text-xs text-rose-600">{error}</p>}
    </div>
  );
}
