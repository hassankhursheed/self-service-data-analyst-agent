import clsx from "clsx";

import { APP_NAME } from "@/lib/brand";

/**
 * The AskData mark ("verified answer"): a question bubble whose bars grow into an
 * answer, with a check badge for an answer that was verified against the data.
 */
export function LogoMark({ size = 32, className }: { size?: number; className?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" className={className} role="img" aria-label={`${APP_NAME} logo`}>
      <circle cx="29" cy="28" r="23" className="fill-brand-600 dark:fill-brand-500" />
      <path d="M12 40 L8 56 L25 47 Z" className="fill-brand-600 dark:fill-brand-500" />
      <rect x="18" y="28" width="6" height="9" rx="2" fill="#fff" />
      <rect x="26.5" y="21" width="6" height="16" rx="2" fill="#fff" />
      <rect x="35" y="15" width="6" height="22" rx="2" fill="#fff" />
      <circle cx="50" cy="49" r="11" className="fill-brand-400 dark:fill-brand-200" stroke="var(--surface)" strokeWidth="3" />
      <path d="M45 49 L48.5 52.5 L55 45.5" stroke="#04342C" strokeWidth="3" fill="none" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function Wordmark({ size = 30, className }: { size?: number; className?: string }) {
  return (
    <span className={clsx("inline-flex items-center gap-2", className)}>
      <LogoMark size={size} />
      <span className="text-lg font-semibold tracking-tight">
        Ask<span className="text-brand-600 dark:text-brand-400">Data</span>
      </span>
    </span>
  );
}
