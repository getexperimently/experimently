import React from 'react';
import Link from 'next/link';
import { useEdition } from '@/contexts/EditionContext';
import { EDITIONS_DOC_PATH, LicenseStatus } from '@/services/edition';

const MONTHS = [
  'January',
  'February',
  'March',
  'April',
  'May',
  'June',
  'July',
  'August',
  'September',
  'October',
  'November',
  'December',
];

/**
 * `12 September 2026`. Hand-rolled rather than `toLocaleDateString` so the
 * copy — and the tests that read it — do not change with the runtime's ICU
 * data or the viewer's locale.
 */
export function formatLicenceDate(date: Date | null): string | null {
  if (!date || isNaN(date.getTime())) return null;
  return `${date.getUTCDate()} ${MONTHS[date.getUTCMonth()]} ${date.getUTCFullYear()}`;
}

interface BannerCopy {
  tone: 'warning' | 'danger';
  title: string;
  body: string;
}

/**
 * What the banner says for each licence state. Only three of the five states
 * produce one: `active` and `none` are the quiet, working cases.
 *
 * The wording is deliberately concrete about consequences. The backend keeps
 * enterprise *reads* working for 30 days after grace ends and refuses every
 * enterprise *write* from the first day of `expired`
 * (`backend/app/core/license.py::LicenseState.allows`), and no licence state
 * ever deletes data — so the copy says exactly that instead of implying that
 * anything is lost.
 */
export function bannerCopy(status: LicenseStatus, expiresOn: string | null): BannerCopy | null {
  switch (status) {
    case 'grace':
      return {
        tone: 'warning',
        title: 'Enterprise licence expired — grace period',
        body:
          (expiresOn
            ? `This licence expired on ${expiresOn}. `
            : 'This licence has expired. ') +
          'Enterprise features keep working during the grace period that follows expiry ' +
          '(14 days unless the licence says otherwise). When it ends they switch off, ' +
          'Community features carry on, and no data is removed.',
      };
    case 'expired':
      return {
        tone: 'danger',
        title: 'Enterprise licence expired — features disabled',
        body:
          (expiresOn ? `This licence expired on ${expiresOn} ` : 'This licence expired ') +
          'and its grace period has ended, so Enterprise features are no longer available ' +
          'in the dashboard. The API still answers Enterprise reads for 30 days after the ' +
          'grace period but refuses Enterprise writes. Community features are unaffected ' +
          'and every record is still in the database.',
      };
    case 'invalid':
      return {
        tone: 'danger',
        title: 'Enterprise licence could not be verified',
        body:
          'The licence key is malformed, signed by an unknown or revoked key, or not yet ' +
          'valid, so it grants nothing. The dashboard is running as Community Edition. ' +
          'No data is affected.',
      };
    default:
      return null;
  }
}

const TONE_CLASSES: Record<BannerCopy['tone'], string> = {
  warning: 'bg-amber-50 border-amber-200 text-amber-900',
  danger: 'bg-red-50 border-red-200 text-red-900',
};

/**
 * Site-wide notice for the licence states that need explaining: `grace`,
 * `expired` and `invalid`. Renders nothing for `none` and `active`.
 *
 * This is not an upsell. It states what is happening, when, and what is not
 * affected, and links to the editions documentation.
 */
export function EditionBanner() {
  const { status, expiresAt } = useEdition();
  const copy = bannerCopy(status, formatLicenceDate(expiresAt));
  if (!copy) return null;

  return (
    <div
      data-testid="edition-banner"
      data-status={status}
      role="status"
      className={`border-b px-4 py-3 text-sm sm:px-6 lg:px-8 ${TONE_CLASSES[copy.tone]}`}
    >
      <div className="max-w-7xl mx-auto flex flex-col gap-1 sm:flex-row sm:items-baseline sm:gap-3">
        <span className="font-semibold whitespace-nowrap">{copy.title}</span>
        <span className="flex-1">{copy.body}</span>
        <Link
          href={EDITIONS_DOC_PATH}
          data-testid="edition-banner-docs"
          className="font-medium underline whitespace-nowrap"
        >
          Editions &amp; licensing
        </Link>
      </div>
    </div>
  );
}

export default EditionBanner;
