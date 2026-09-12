import React from 'react';
import Link from 'next/link';
import { useEdition } from '@/contexts/EditionContext';
import { Edition, LicenseStatus } from '@/services/edition';

interface WordmarkProps {
  href?: string | null;
  /** Show the edition pill next to the name. */
  edition?: boolean;
  className?: string;
}

interface PillLook {
  label: string;
  title: string;
  className: string;
}

const NEUTRAL = 'border-slate-200 bg-slate-50 text-slate-500';
const ENTERPRISE = 'border-indigo-200 bg-indigo-50 text-indigo-700';
const WARNING = 'border-amber-300 bg-amber-50 text-amber-800';
const DANGER = 'border-red-300 bg-red-50 text-red-800';

/**
 * How the pill reads for each of the five licence states.
 *
 * `expired` still says `EE`, because the instance *is* an enterprise
 * deployment — the pill's job is to tell an operator which build they are
 * looking at, and its title says what the licence is doing. Only a genuinely
 * unlicensed instance reads `CE`.
 *
 * `invalid` is checked before the edition: the API reports a tampered,
 * revoked or not-yet-valid key as `{edition: 'ce', status: 'invalid'}`
 * (`LicenseState.is_enterprise` excludes INVALID on purpose, so a probe
 * learns nothing from a bad key), and a neutral `CE` pill directly above a
 * red "licence could not be verified" banner read as two different stories.
 */
export function pillLook(edition: Edition, status: LicenseStatus): PillLook {
  if (status === 'invalid') {
    return {
      label: 'EE',
      title: 'Enterprise licence could not be verified',
      className: DANGER,
    };
  }
  if (edition !== 'enterprise') {
    return { label: 'CE', title: 'Community Edition', className: NEUTRAL };
  }
  switch (status) {
    case 'grace':
      return {
        label: 'EE',
        title: 'Enterprise Edition — licence expired, in grace period',
        className: WARNING,
      };
    case 'expired':
      return {
        label: 'EE',
        title: 'Enterprise Edition — licence expired, features disabled',
        className: DANGER,
      };
    default:
      return { label: 'EE', title: 'Enterprise Edition', className: ENTERPRISE };
  }
}

/**
 * "Experimently" wordmark with the edition pill. The pill reflects the answer
 * from `GET /api/v1/edition`; with no `EditionProvider` above it — or with the
 * backend unreachable — it reads `CE`.
 */
export function Wordmark({ href = '/', edition = true, className = '' }: WordmarkProps) {
  const { edition: currentEdition, status, isLoading } = useEdition();
  const pill = pillLook(currentEdition, status);
  // No pill until the probe has answered: the provider's initial state is
  // Community, so a licensed instance used to paint `CE` on every full page
  // load and flip to `EE` when /api/v1/edition resolved.
  const showPill = edition && !isLoading;

  const inner = (
    <span className={`inline-flex items-center gap-2 ${className}`}>
      <span
        aria-hidden="true"
        className="inline-flex h-7 w-7 items-center justify-center rounded-md bg-blue-600 text-sm font-bold text-white"
      >
        E
      </span>
      <span className="text-lg font-semibold tracking-tight text-slate-900">Experimently</span>
      {showPill && (
        <span
          data-testid="edition-pill"
          data-edition={currentEdition}
          data-status={status}
          className={`rounded-full border px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${pill.className}`}
          title={pill.title}
        >
          {pill.label}
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
