import React from 'react';
import Link from 'next/link';
import { PageTitle } from '@/components/PageTitle';
import { useEdition } from '@/contexts/EditionContext';
import { EDITIONS_DOC_PATH } from '@/services/edition';

export interface EnterpriseFeatureNoticeProps {
  /** Human name of the thing that is not available, e.g. `Workspaces`. */
  title: string;
  /** Licence feature name, e.g. `workspaces`. Shown so support can match it. */
  feature: string;
  /** One line on what the feature does, for someone who has never seen it. */
  description: string;
}

/**
 * What an Enterprise route renders in a build that has no Enterprise tree.
 *
 * It is a statement of fact plus a documentation link, not a sales page: the
 * route exists, the feature is not in this build, here is where the editions
 * are described. The wording changes with the licence state so a customer
 * whose licence lapsed is not told they never had the feature.
 */
export function EnterpriseFeatureNotice({
  title,
  feature,
  description,
}: EnterpriseFeatureNoticeProps) {
  const { status } = useEdition();

  const reason =
    status === 'expired'
      ? 'The Enterprise licence on this instance has expired, so this page is unavailable.'
      : status === 'grace'
        ? 'This build does not include the Enterprise modules, so the page cannot be shown ' +
          'even though the licence is still inside its grace period.'
        : status === 'invalid'
          ? 'The Enterprise licence on this instance could not be verified, so this page is ' +
            'unavailable.'
          : 'This is the Community Edition build, which does not include the Enterprise modules.';

  return (
    <div data-testid="enterprise-feature-notice" data-feature={feature} className="p-6">
      <PageTitle title={`${title} — Enterprise`} />
      <div className="max-w-2xl mx-auto mt-12 rounded-lg border border-slate-200 bg-white p-8 text-center">
        <p className="text-xs font-semibold uppercase tracking-wider text-slate-400">Enterprise</p>
        <h1 className="mt-2 text-xl font-semibold text-slate-900">{title}</h1>
        <p className="mt-3 text-sm text-slate-600">{description}</p>
        <p className="mt-4 text-sm text-slate-500">{reason}</p>
        <p className="mt-6 text-sm">
          <Link href={EDITIONS_DOC_PATH} className="font-medium text-blue-700 underline">
            Compare Community and Enterprise
          </Link>
        </p>
      </div>
    </div>
  );
}

/**
 * Build the page component an Enterprise route falls back to. Used by every
 * module under `src/ee-stub/pages/`, which is what `@ee/pages/*` resolves to
 * in a Community build.
 */
export function enterprisePageStub(props: EnterpriseFeatureNoticeProps): React.FC {
  const Stub: React.FC = () => <EnterpriseFeatureNotice {...props} />;
  Stub.displayName = `EnterpriseStub(${props.title})`;
  return Stub;
}

/**
 * Gate a real Enterprise page on its licence feature.
 *
 * The sidebar only hides the link; a bookmarked or typed URL still reaches the
 * page, whose first API call is then refused with `feature_not_licensed`.
 * Wrapped, the page renders the same notice the Community stub shows, and
 * nothing at all while the edition is still being probed -- a licensed page
 * must not flash the "Enterprise feature" notice before the answer arrives.
 */
export function withFeature<P extends object>(
  Page: React.ComponentType<P>,
  notice: EnterpriseFeatureNoticeProps,
): React.FC<P> {
  const Gated: React.FC<P> = (props) => {
    const { isLoading, hasFeature } = useEdition();
    if (isLoading) return null;
    if (!hasFeature(notice.feature)) return <EnterpriseFeatureNotice {...notice} />;
    return <Page {...props} />;
  };
  Gated.displayName = `withFeature(${Page.displayName ?? Page.name ?? 'Page'})`;
  return Gated;
}

export default EnterpriseFeatureNotice;
