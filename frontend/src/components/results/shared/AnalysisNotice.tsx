import React from 'react';
import { AnalysisStatus } from '@/types/analysis';

interface AnalysisNoticeProps {
  status?: AnalysisStatus | null;
  notice?: string | null;
}

/** An issue link in a notice, e.g. https://github.com/<org>/<repo>/issues/231. */
const ISSUE_URL = /https:\/\/github\.com\/[\w.-]+\/[\w.-]+\/issues\/(\d+)/g;

/** The label already says "Beta", so a leading "Beta:" in the text is dropped. */
const LEADING_BETA = /^\s*beta\s*[:–—-]\s*/i;

/** Split the notice into text and issue links, in order. */
function noticeParts(text: string): React.ReactNode[] {
  const parts: React.ReactNode[] = [];
  const pattern = new RegExp(ISSUE_URL.source, 'g');
  let last = 0;
  let match: RegExpExecArray | null;
  // An `exec` loop rather than `matchAll`: tsconfig targets es5.
  while ((match = pattern.exec(text)) !== null) {
    const start = match.index;
    if (start > last) parts.push(text.slice(last, start));
    parts.push(
      <a
        key={start}
        href={match[0]}
        target="_blank"
        rel="noopener noreferrer"
        className="font-medium text-amber-900 underline hover:no-underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-amber-900"
      >
        issue #{match[1]}
      </a>
    );
    last = start + match[0].length;
  }
  if (last < text.length) parts.push(text.slice(last));
  return parts;
}

/**
 * The beta notice an analysis response carries (`analysis_status` /
 * `analysis_notice`). Renders nothing unless the status is "beta" and there is
 * a notice. The explanation is visible text, not a tooltip, and the region is
 * not an alert: it qualifies the numbers, it does not interrupt.
 */
export function AnalysisNotice({ status, notice }: AnalysisNoticeProps) {
  if (status !== 'beta' || !notice) return null;

  const text = notice.replace(LEADING_BETA, '');

  return (
    <section
      aria-label="Beta analysis notice"
      data-testid="analysis-notice"
      className="rounded-lg border border-amber-300 bg-amber-50 p-4"
    >
      <p className="text-sm text-amber-900">
        <span
          data-testid="analysis-notice-label"
          className="mr-2 inline-flex items-center rounded-full bg-amber-100 px-2 py-0.5 text-xs font-semibold text-amber-800 ring-1 ring-inset ring-amber-300"
        >
          Beta
        </span>
        <span data-testid="analysis-notice-text">{noticeParts(text)}</span>
      </p>
    </section>
  );
}
