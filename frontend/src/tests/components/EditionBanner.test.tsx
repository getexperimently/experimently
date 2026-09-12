import React from 'react';
import { render, screen } from '@testing-library/react';
import { EditionBanner, bannerCopy, formatLicenceDate } from '@/components/EditionBanner';
import { EnterpriseFeatureNotice, withFeature } from '@/components/EnterpriseFeatureNotice';
import { Wordmark, pillLook } from '@/components/Wordmark';
import { EditionProvider, __resetEditionCache } from '@/contexts/EditionContext';
import {
  COMMUNITY_EDITION,
  EditionInfo,
  EditionService,
  FEATURES,
  LicenseStatus,
} from '@/services/edition';

jest.mock('next/link', () => {
  const MockLink = ({ children, href, ...rest }: { children: React.ReactNode; href: string }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  );
  MockLink.displayName = 'MockLink';
  return MockLink;
});

jest.mock('next/head', () => {
  const MockHead = ({ children }: { children: React.ReactNode }) => <>{children}</>;
  MockHead.displayName = 'MockHead';
  return MockHead;
});

function info(status: LicenseStatus, overrides: Partial<EditionInfo> = {}): EditionInfo {
  // As the API actually reports each state: `invalid` comes back as edition
  // 'ce' with no features (LicenseState.is_enterprise excludes INVALID), not as
  // an enterprise body — a fixture that said otherwise made the pill's invalid
  // branch look reachable when it was not.
  const enterprise = status !== 'none' && status !== 'invalid';
  return {
    edition: enterprise ? 'enterprise' : 'ce',
    features: enterprise ? [FEATURES.RBAC] : [],
    status,
    expires_at: status === 'none' ? null : '2026-09-12T00:00:00Z',
    version: '1.0.0',
    ...overrides,
  };
}

function renderWith(edition: EditionInfo, node: React.ReactNode) {
  return render(<EditionProvider initial={edition}>{node}</EditionProvider>);
}

describe('formatLicenceDate', () => {
  it('formats in UTC so the copy does not move with the viewer', () => {
    expect(formatLicenceDate(new Date('2026-09-12T23:30:00Z'))).toBe('12 September 2026');
    expect(formatLicenceDate(new Date('2027-01-01T00:00:00Z'))).toBe('1 January 2027');
  });

  it('is null for a missing or unparseable date', () => {
    expect(formatLicenceDate(null)).toBeNull();
    expect(formatLicenceDate(new Date('nonsense'))).toBeNull();
  });
});

describe('bannerCopy', () => {
  it('says nothing in the two quiet states', () => {
    expect(bannerCopy('none', null)).toBeNull();
    expect(bannerCopy('active', '1 January 2027')).toBeNull();
  });

  it('names the date and says features keep working during grace', () => {
    const copy = bannerCopy('grace', '12 September 2026')!;
    expect(copy.tone).toBe('warning');
    expect(copy.body).toContain('12 September 2026');
    expect(copy.body).toContain('keep working');
    expect(copy.body).toContain('no data is removed');
  });

  it('says what expiry actually does — reads for 30 days, writes refused, nothing lost', () => {
    const copy = bannerCopy('expired', '12 September 2026')!;
    expect(copy.tone).toBe('danger');
    expect(copy.body).toContain('30 days');
    expect(copy.body).toContain('refuses Enterprise writes');
    expect(copy.body).toContain('still in the database');
  });

  it('explains an invalid licence without implying data loss', () => {
    const copy = bannerCopy('invalid', null)!;
    expect(copy.title).toContain('could not be verified');
    expect(copy.body).toContain('Community Edition');
    expect(copy.body).toContain('No data is affected');
  });

  it('still reads sensibly with no expiry date', () => {
    expect(bannerCopy('grace', null)!.body).toContain('This licence has expired.');
    expect(bannerCopy('expired', null)!.body).toContain('This licence expired ');
  });
});

describe('<EditionBanner />', () => {
  it.each(['none', 'active'] as LicenseStatus[])('renders nothing for %s', (status) => {
    const { container } = renderWith(info(status), <EditionBanner />);
    expect(container).toBeEmptyDOMElement();
  });

  it.each(['grace', 'expired', 'invalid'] as LicenseStatus[])('renders for %s', (status) => {
    renderWith(info(status), <EditionBanner />);
    const banner = screen.getByTestId('edition-banner');
    expect(banner).toHaveAttribute('data-status', status);
    expect(banner).toHaveAttribute('role', 'status');
    expect(screen.getByTestId('edition-banner-docs')).toHaveAttribute('href', '/docs/editions');
  });

  it('shows the expiry date in the grace banner', () => {
    renderWith(info('grace'), <EditionBanner />);
    expect(screen.getByTestId('edition-banner')).toHaveTextContent('12 September 2026');
  });
});

describe('the edition pill', () => {
  it.each([
    ['none', 'CE', 'Community Edition'],
    ['active', 'EE', 'Enterprise Edition'],
    ['grace', 'EE', 'grace period'],
    ['expired', 'EE', 'features disabled'],
    ['invalid', 'EE', 'could not be verified'],
  ] as [LicenseStatus, string, string][])(
    '%s reads %s',
    (status, label, titleFragment) => {
      const look = pillLook(info(status).edition, status);
      expect(look.label).toBe(label);
      expect(look.title).toContain(titleFragment);
    },
  );

  it('renders the real edition from the context', () => {
    renderWith(info('grace'), <Wordmark href={null} />);
    const pill = screen.getByTestId('edition-pill');
    expect(pill).toHaveTextContent('EE');
    expect(pill).toHaveAttribute('data-edition', 'enterprise');
    expect(pill).toHaveAttribute('data-status', 'grace');
  });

  it('shows no pill while the probe is outstanding', () => {
    // The provider's initial state is Community; painting `CE` on a licensed
    // instance and flipping to `EE` a moment later is worse than a short gap.
    __resetEditionCache();
    const pending = jest
      .spyOn(EditionService, 'get')
      .mockReturnValue(new Promise(() => undefined)); // never resolves
    try {
      render(
        <EditionProvider>
          <Wordmark href={null} />
        </EditionProvider>,
      );
      expect(screen.queryByTestId('edition-pill')).not.toBeInTheDocument();
    } finally {
      pending.mockRestore();
      __resetEditionCache();
    }
  });

  it('reads CE with no provider — the unreachable-backend default', () => {
    render(<Wordmark href={null} />);
    const pill = screen.getByTestId('edition-pill');
    expect(pill).toHaveTextContent('CE');
    expect(pill).toHaveAttribute('data-status', 'none');
  });

  it('can still be suppressed', () => {
    renderWith(COMMUNITY_EDITION, <Wordmark href={null} edition={false} />);
    expect(screen.queryByTestId('edition-pill')).not.toBeInTheDocument();
  });
});

describe('<EnterpriseFeatureNotice />', () => {
  const props = {
    title: 'Workspaces',
    feature: FEATURES.WORKSPACES,
    description: 'Separate teams into workspaces.',
  };

  it('says this is a Community build, and links to the editions docs', () => {
    renderWith(COMMUNITY_EDITION, <EnterpriseFeatureNotice {...props} />);
    const notice = screen.getByTestId('enterprise-feature-notice');
    expect(notice).toHaveAttribute('data-feature', 'workspaces');
    expect(notice).toHaveTextContent('Community Edition build');
    expect(screen.getByRole('link', { name: /compare community and enterprise/i })).toHaveAttribute(
      'href',
      '/docs/editions',
    );
  });

  it('tells a lapsed customer their licence expired, not that they never had it', () => {
    renderWith(info('expired'), <EnterpriseFeatureNotice {...props} />);
    expect(screen.getByTestId('enterprise-feature-notice')).toHaveTextContent(
      'licence on this instance has expired',
    );
  });

  it('distinguishes an unverifiable licence', () => {
    renderWith(info('invalid'), <EnterpriseFeatureNotice {...props} />);
    expect(screen.getByTestId('enterprise-feature-notice')).toHaveTextContent(
      'could not be verified',
    );
  });
});

describe('withFeature', () => {
  const Real: React.FC = () => <div data-testid="real-page">the real page</div>;
  const Gated = withFeature(Real, {
    title: 'Custom Roles',
    feature: FEATURES.RBAC,
    description: 'Roles beyond the built-in four.',
  });

  it('renders the real page when the licence allows the feature', () => {
    renderWith(info('active'), <Gated />);
    expect(screen.getByTestId('real-page')).toBeInTheDocument();
  });

  it('renders the Enterprise notice, not the page, when the licence does not', () => {
    // The sidebar only hides the link; a bookmarked URL reached the page,
    // whose first API call was then refused with feature_not_licensed.
    renderWith(info('active', { features: [FEATURES.WORKSPACES] }), <Gated />);
    expect(screen.queryByTestId('real-page')).not.toBeInTheDocument();
    expect(screen.getByRole('heading', { name: /Custom Roles/ })).toBeInTheDocument();
  });

  it('renders nothing while the edition is still being probed', () => {
    __resetEditionCache();
    const pending = jest
      .spyOn(EditionService, 'get')
      .mockReturnValue(new Promise(() => undefined));
    try {
      render(
        <EditionProvider>
          <Gated />
        </EditionProvider>,
      );
      expect(screen.queryByTestId('real-page')).not.toBeInTheDocument();
      expect(screen.queryByRole('heading', { name: /Custom Roles/ })).not.toBeInTheDocument();
    } finally {
      pending.mockRestore();
      __resetEditionCache();
    }
  });
});
