"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { Alert, Button, Field, Input } from "@/components/ui";
import type { ApiErrorBody, User } from "@/lib/types";

export function LoginForm({ expired }: { expired: boolean }) {
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    if (!username.trim() || !password) {
      setError("Enter your username and password.");
      return;
    }
    setBusy(true);
    try {
      const response = await fetch("/api/session", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: username.trim(), password }),
      });
      const body = (await response.json().catch(() => null)) as (ApiErrorBody & { user?: User }) | null;
      if (!response.ok) {
        const code = body?.error?.code;
        setError(
          code === "RATE_LIMITED"
            ? "Too many sign-in attempts. Please wait a minute and try again."
            : (body?.error?.message ?? "Sign-in failed. Please try again."),
        );
        setPassword("");
        return;
      }
      router.replace(body?.user?.role === "admin" ? "/admin/users" : "/");
      router.refresh();
    } catch {
      setError("Could not reach the server. Check your connection.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="mt-8 space-y-5" noValidate>
      {expired && !error && (
        <Alert tone="amber" title="Session ended">
          Your session has expired. Please sign in again.
        </Alert>
      )}
      {error && <Alert title="Could not sign in">{error}</Alert>}
      <Field label="Username">
        <Input
          name="username"
          autoComplete="username"
          autoFocus
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          placeholder="e.g. sales.europe"
        />
      </Field>
      <Field label="Password">
        <Input
          name="password"
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
      </Field>
      <Button type="submit" loading={busy} className="w-full">
        Sign in
      </Button>
    </form>
  );
}
