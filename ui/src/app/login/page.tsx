import { BarChart3, Lock, ShieldCheck, Sparkles } from "lucide-react";

import { LoginForm } from "./login-form";

export default async function LoginPage({ searchParams }: { searchParams: Promise<{ expired?: string }> }) {
  const { expired } = await searchParams;
  return (
    <main className="grid min-h-dvh lg:grid-cols-[1.1fr_1fr]">
      <section className="relative hidden overflow-hidden bg-gradient-to-br from-brand-700 via-brand-600 to-indigo-500 p-12 text-white lg:flex lg:flex-col lg:justify-between">
        <div className="absolute -right-24 -top-24 size-96 rounded-full bg-white/10 blur-3xl" aria-hidden />
        <div className="absolute -bottom-32 left-10 size-96 rounded-full bg-cyan-300/20 blur-3xl" aria-hidden />
        <div className="relative flex items-center gap-3">
          <div className="rounded-xl bg-white/15 p-2 backdrop-blur">
            <BarChart3 className="size-6" />
          </div>
          <span className="text-lg font-semibold tracking-tight">Northwind Analyst</span>
        </div>
        <div className="relative max-w-lg space-y-6">
          <h1 className="text-4xl font-semibold leading-tight tracking-tight">
            Ask your sales data a question. Get a trustworthy answer.
          </h1>
          <ul className="space-y-3 text-white/85">
            <li className="flex gap-3">
              <Sparkles className="mt-0.5 size-5 shrink-0" /> Plain-language questions become checked, read-only SQL.
            </li>
            <li className="flex gap-3">
              <ShieldCheck className="mt-0.5 size-5 shrink-0" /> You only ever see the data your role and region allow.
            </li>
            <li className="flex gap-3">
              <Lock className="mt-0.5 size-5 shrink-0" /> Every answer shows its SQL, date range and assumptions.
            </li>
          </ul>
        </div>
        <p className="relative text-xs text-white/60">Northwind Traders is a fictional company. All data is sample data.</p>
      </section>
      <section className="flex items-center justify-center px-4 py-12 sm:px-8">
        <div className="w-full max-w-sm">
          <div className="mb-8 flex items-center gap-3 lg:hidden">
            <div className="rounded-xl bg-brand-600 p-2 text-white">
              <BarChart3 className="size-5" />
            </div>
            <span className="text-lg font-semibold">Northwind Analyst</span>
          </div>
          <h2 className="text-2xl font-semibold tracking-tight">Sign in</h2>
          <p className="text-muted mt-1 text-sm">Use the account your administrator gave you.</p>
          <LoginForm expired={expired === "1"} />
        </div>
      </section>
    </main>
  );
}
