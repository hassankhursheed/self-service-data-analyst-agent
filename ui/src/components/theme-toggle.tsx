"use client";

import { Monitor, Moon, Sun } from "lucide-react";
import { useEffect, useSyncExternalStore } from "react";

import {
  applyTheme,
  readThemeChoice,
  setThemeChoice,
  subscribeTheme,
  THEME_CHOICES,
  type ThemeChoice,
} from "@/lib/theme";

const LABELS: Record<ThemeChoice, string> = { system: "System theme", light: "Light theme", dark: "Dark theme" };
const ICONS = { system: Monitor, light: Sun, dark: Moon };

/** Cycles system → light → dark. "System" follows the operating system live. */
export function ThemeToggle() {
  const choice = useSyncExternalStore<ThemeChoice>(subscribeTheme, readThemeChoice, () => "system");

  useEffect(() => {
    if (choice !== "system" || typeof window.matchMedia !== "function") return;
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const follow = () => applyTheme("system");
    media.addEventListener("change", follow);
    return () => media.removeEventListener("change", follow);
  }, [choice]);

  function next() {
    const index = THEME_CHOICES.indexOf(choice);
    setThemeChoice(THEME_CHOICES[(index + 1) % THEME_CHOICES.length] ?? "system");
  }

  const Icon = ICONS[choice];
  return (
    <button
      type="button"
      onClick={next}
      className="text-muted rounded-lg p-2 hover:bg-muted hover:text-[var(--text)]"
      aria-label={`${LABELS[choice]}. Change theme`}
      title={LABELS[choice]}
      data-testid="theme-toggle"
    >
      <Icon className="size-4" />
    </button>
  );
}
