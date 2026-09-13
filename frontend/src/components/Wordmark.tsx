import React from 'react';
import Link from 'next/link';

interface WordmarkProps {
  href?: string | null;
  className?: string;
}

/** "Experimently" wordmark. A wordmark is a wordmark: it carries no status. */
export function Wordmark({ href = '/', className = '' }: WordmarkProps) {
  const inner = (
    <span className={`inline-flex items-center gap-2 ${className}`}>
      <span
        aria-hidden="true"
        className="inline-flex h-7 w-7 items-center justify-center rounded-md bg-blue-600 text-sm font-bold text-white"
      >
        E
      </span>
      <span className="text-lg font-semibold tracking-tight text-slate-900">Experimently</span>
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
