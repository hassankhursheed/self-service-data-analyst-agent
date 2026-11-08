// Light, dark or system theme. The choice is a per-browser convenience in localStorage;
// "system" follows the operating system and updates when it changes.
export type ThemeChoice = "system" | "light" | "dark";

export const THEME_KEY = "askdata-theme";
export const THEME_CHOICES: ThemeChoice[] = ["system", "light", "dark"];

export function readThemeChoice(): ThemeChoice {
  try {
    const saved = window.localStorage.getItem(THEME_KEY);
    return saved === "light" || saved === "dark" ? saved : "system";
  } catch {
    return "system";
  }
}

export function resolveTheme(choice: ThemeChoice, systemDark: boolean): "light" | "dark" {
  return choice === "system" ? (systemDark ? "dark" : "light") : choice;
}

export function systemPrefersDark(): boolean {
  return typeof window.matchMedia === "function" && window.matchMedia("(prefers-color-scheme: dark)").matches;
}

export function applyTheme(choice: ThemeChoice): void {
  const dark = systemPrefersDark();
  document.documentElement.dataset.theme = resolveTheme(choice, dark);
  try {
    if (choice === "system") window.localStorage.removeItem(THEME_KEY);
    else window.localStorage.setItem(THEME_KEY, choice);
  } catch {
    // Storage can be blocked; the theme still applies for this page.
  }
}

// Inline in <head>: the same logic as readThemeChoice + resolveTheme, before React loads.
export const THEME_INIT_SCRIPT = `(function(){try{var s=localStorage.getItem("${THEME_KEY}");var d=window.matchMedia("(prefers-color-scheme: dark)").matches;document.documentElement.dataset.theme=s==="light"||s==="dark"?s:(d?"dark":"light");}catch(e){document.documentElement.dataset.theme=window.matchMedia("(prefers-color-scheme: dark)").matches?"dark":"light";}})();`;

// A tiny store so components can read the choice with useSyncExternalStore.
const listeners = new Set<() => void>();

export function subscribeTheme(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function setThemeChoice(choice: ThemeChoice): void {
  applyTheme(choice);
  listeners.forEach((listener) => listener());
}
