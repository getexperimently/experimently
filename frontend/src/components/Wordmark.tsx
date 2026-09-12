import React from 'react';
import Link from 'next/link';

interface WordmarkProps {
  href?: string | null;
  /** Show the edition pill next to the name. */
  edition?: boolean;
  className?: string;
}

/**
 * "Experimently" wordmark with the CE edition pill placeholder. The pill is
 * where edition gating (P2) will render `CE` / `Enterprise` state.
 */
export function Wordmark({ href = '/', edition = true, className = '' }: WordmarkProps) {
  const inner = (
    <span className={`inline-flex items-center gap-2 ${className}`}>
      <span
        aria-hidden="true"
        className="inline-flex h-7 w-7 items-center justify-center rounded-md bg-blue-600 text-sm font-bold text-white"
      >
        E
      </span>
      <span className="text-lg font-semibold tracking-tight text-slate-900">Experimently</span>
      {edition && (
        <span
          data-testid="edition-pill"
          className="rounded-full border border-slate-200 bg-slate-50 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-slate-500"
          title="Community Edition"
        >
          CE
        </span>
      )}
    </span>
  );

  if (!href) return inner;
  return (
    <Link href={href} className="inline-flex items-center" aria-label="Experimently home">
      {inner}
    </Link>
  );
}

export default Wordmark;
