import { BadgeCheck, Database, Lock, ShieldCheck, Sparkles } from "lucide-react";

import { LogoMark, Wordmark } from "@/components/logo";
import { ThemeToggle } from "@/components/theme-toggle";
import { APP_NAME, DATASET_NAME, FICTIONAL_NOTE, TAGLINE } from "@/lib/brand";

import { LoginForm } from "./login-form";

const POINTS = [
  { icon: Sparkles, text: "Plain-language questions become checked, read-only SQL." },
  { icon: ShieldCheck, text: "You only ever see the data your role and region allow." },
  { icon: Lock, text: "Every answer shows its SQL, period and assumptions." },
];

/** A sample answer card: what a verified answer looks like (illustration only). */
function PreviewCard() {
  return (
    <div className="max-w-md rounded-2xl bg-white/95 p-4 text-slate-800 shadow-2xl ring-1 ring-black/5" aria-hidden>
      <p className="ml-auto w-fit rounded-xl rounded-br-sm bg-brand-600 px-3 py-1.5 text-sm text-white">
        Top 3 categories by revenue last quarter
      </p>
      <div className="mt-3 space-y-2">
        {[
          ["Beverages", 100],
          ["Confections", 49],
          ["Dairy Products", 48],
        ].map(([label, width]) => (
          <div key={label} className="flex items-center gap-2 text-xs">
            <span className="w-24 shrink-0 text-slate-500">{label}</span>
            <span className="h-2.5 rounded-full bg-brand-500" style={{ width: `${width}%` }} />
          </div>
        ))}
      </div>
      <div className="mt-3 flex flex-wrap gap-1.5 text-[11px] font-medium">
        <span className="inline-flex items-center gap-1 rounded-full bg-brand-50 px-2 py-0.5 text-brand-700">
          <BadgeCheck className="size-3" /> Verified against the data
        </span>
        <span className="rounded-full bg-slate-100 px-2 py-0.5 text-slate-600">Q1 2025</span>
        <span className="rounded-full bg-slate-100 px-2 py-0.5 text-slate-600">Read-only</span>
      </div>
    </div>
  );
}

export default async function LoginPage({ searchParams }: { searchParams: Promise<{ expired?: string }> }) {
  const { expired } = await searchParams;
  return (
    <main className="grid min-h-dvh lg:grid-cols-[1.1fr_1fr]">
      <section className="relative hidden overflow-hidden bg-gradient-to-br from-brand-900 via-brand-700 to-brand-500 p-12 text-white lg:flex lg:flex-col lg:justify-between">
        <div className="absolute -right-24 -top-24 size-96 rounded-full bg-brand-200/20 blur-3xl" aria-hidden />
        <div className="absolute -bottom-32 left-10 size-96 rounded-full bg-emerald-300/15 blur-3xl" aria-hidden />
        <div className="relative flex items-center gap-3">
          <span className="rounded-2xl bg-white p-1.5 shadow-lg">
            <LogoMark size={34} />
          </span>
          <span className="text-xl font-semibold tracking-tight">{APP_NAME}</span>
        </div>
        <div className="relative max-w-lg space-y-7">
          <h1 className="text-4xl font-semibold leading-tight tracking-tight">{TAGLINE}</h1>
          <ul className="space-y-3 text-white/85">
            {POINTS.map(({ icon: Icon, text }) => (
              <li key={text} className="flex gap-3">
                <Icon className="mt-0.5 size-5 shrink-0 text-brand-200" /> {text}
              </li>
            ))}
          </ul>
          <PreviewCard />
        </div>
        <p className="relative flex items-center gap-2 text-xs text-white/65">
          <Database className="size-3.5" aria-hidden /> Dataset: {DATASET_NAME}. {FICTIONAL_NOTE}
        </p>
      </section>
      <section className="relative flex items-center justify-center px-4 py-12 sm:px-8">
        <div className="absolute right-4 top-4">
          <ThemeToggle />
        </div>
        <div className="w-full max-w-sm">
          <div className="mb-8 lg:hidden">
            <Wordmark size={34} />
            <p className="text-muted mt-2 text-sm">{TAGLINE}</p>
          </div>
          <h2 className="text-2xl font-semibold tracking-tight">Sign in</h2>
          <p className="text-muted mt-1 text-sm">Use the account your administrator gave you.</p>
          <LoginForm expired={expired === "1"} />
          <p className="text-muted mt-8 text-xs lg:hidden">
            Dataset: {DATASET_NAME}. {FICTIONAL_NOTE}
          </p>
        </div>
      </section>
    </main>
  );
}
