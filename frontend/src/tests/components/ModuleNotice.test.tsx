import React from 'react';
import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {
  ModuleNotice,
  ModuleUnavailableNotice,
  modulePageStub,
  withModule,
} from '@/components/ModuleNotice';
import { ModulesProvider, __resetModulesCache } from '@/contexts/ModulesContext';
import { CORE_PROFILE, MODULES, ModulesInfo, ModulesService } from '@/services/modules';

// Only `ModulesService.get` is replaced; MODULES, CORE_PROFILE and the rest
// stay real. The seeded providers below never call it.
jest.mock('@/services/modules', () => {
  const actual = jest.requireActual('@/services/modules');
  return { ...actual, ModulesService: { get: jest.fn() } };
});

const mockGet = ModulesService.get as jest.Mock;

beforeEach(() => {
  __resetModulesCache();
  mockGet.mockReset();
});

jest.mock('next/head', () => {
  const MockHead = ({ children }: { children: React.ReactNode }) => <>{children}</>;
  MockHead.displayName = 'MockHead';
  return MockHead;
});

jest.mock('next/link', () => {
  const MockLink = ({
    children,
    href,
    ...rest
  }: { children: React.ReactNode; href: string; [key: string]: unknown }) => (
    <a href={href} {...rest}>{children}</a>
  );
  MockLink.displayName = 'MockLink';
  return MockLink;
});

const notice = {
  title: 'Workspaces',
  module: MODULES.WORKSPACES,
  description: 'Separate teams into workspaces.',
};

function full(overrides: Partial<ModulesInfo> = {}): ModulesInfo {
  return { profile: 'full', modules: [MODULES.WORKSPACES], version: '1.0.0', ...overrides };
}

describe('ModuleNotice', () => {
  it('states that the module is not installed and links to the modules guide', () => {
    render(<ModuleNotice {...notice} />);
    const box = screen.getByTestId('module-notice');
    expect(box).toHaveAttribute('data-module', 'workspaces');
    expect(box).toHaveTextContent(
      'The Workspaces module is not installed in this deployment. Modules are part of the full profile; see the modules guide.',
    );
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Workspaces');
    expect(screen.getByText('Separate teams into workspaces.')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'modules guide' })).toHaveAttribute('href', '/docs/modules');
  });

  it('is a statement of fact, not a sales page', () => {
    render(<ModuleNotice {...notice} />);
    const text = screen.getByTestId('module-notice').textContent ?? '';
    expect(text).not.toMatch(/upgrade|contact|sales|pricing|buy|plan/i);
  });

  it('marks itself as the not-installed state', () => {
    render(<ModuleNotice {...notice} />);
    expect(screen.getByTestId('module-notice')).toHaveAttribute('data-state', 'not-installed');
  });
});

describe('ModuleUnavailableNotice', () => {
  it('says the check failed, not that the module is missing', () => {
    render(<ModuleUnavailableNotice {...notice} onRetry={() => undefined} />);
    const box = screen.getByTestId('module-notice');
    expect(box).toHaveAttribute('data-state', 'unreachable');
    expect(box).toHaveAttribute('data-module', 'workspaces');
    expect(box).toHaveTextContent('could not reach the API');
    expect(box).not.toHaveTextContent('is not installed in this deployment');
  });

  it('offers a retry, and disables it while one is in flight', () => {
    const onRetry = jest.fn();
    const { rerender } = render(<ModuleUnavailableNotice {...notice} onRetry={onRetry} />);
    const button = screen.getByTestId('module-notice-retry');
    expect(button).toBeEnabled();
    expect(button).toHaveTextContent('Try again');

    rerender(<ModuleUnavailableNotice {...notice} onRetry={onRetry} retrying />);
    expect(screen.getByTestId('module-notice-retry')).toBeDisabled();
    expect(screen.getByTestId('module-notice-retry')).toHaveTextContent('Checking');
  });
});

describe('modulePageStub', () => {
  it('builds a page that renders the notice, named after the route', () => {
    const Stub = modulePageStub(notice);
    expect(Stub.displayName).toBe('ModuleStub(Workspaces)');
    render(<Stub />);
    expect(screen.getByTestId('module-notice')).toBeInTheDocument();
  });
});

describe('withModule', () => {
  function Page({ greeting = 'hello' }: { greeting?: string }) {
    return <div data-testid="real-page">{greeting}</div>;
  }
  const Gated = withModule(Page, notice);

  it('names the wrapper after the page', () => {
    expect(Gated.displayName).toBe('withModule(Page)');
  });

  it('renders the page when the module is installed', () => {
    render(
      <ModulesProvider initial={full()}>
        <Gated greeting="hi" />
      </ModulesProvider>,
    );
    expect(screen.getByTestId('real-page')).toHaveTextContent('hi');
    expect(screen.queryByTestId('module-notice')).not.toBeInTheDocument();
  });

  it('renders the notice when the module is not installed', () => {
    render(
      <ModulesProvider initial={CORE_PROFILE}>
        <Gated />
      </ModulesProvider>,
    );
    expect(screen.getByTestId('module-notice')).toBeInTheDocument();
    expect(screen.queryByTestId('real-page')).not.toBeInTheDocument();
  });

  it('renders the notice on a full profile that lacks this module', () => {
    render(
      <ModulesProvider initial={full({ modules: [MODULES.RBAC] })}>
        <Gated />
      </ModulesProvider>,
    );
    expect(screen.getByTestId('module-notice')).toBeInTheDocument();
  });

  it('renders nothing while the modules are still being probed', () => {
    // An installed page must not flash the notice before the answer arrives.
    mockGet.mockReturnValue(new Promise(() => {}));
    const { container } = render(
      <ModulesProvider>
        <Gated />
      </ModulesProvider>,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it('does not claim "not installed" when the probe itself failed', async () => {
    // One 502, or a probe that hits the ten-second timeout, resolves the
    // context to core with `error` set. Reading only `hasModule` then told a
    // full-profile operator their module was not installed -- and the retry
    // back-off could leave that on screen for minutes.
    mockGet.mockRejectedValue(new TypeError('Failed to fetch'));
    render(
      <ModulesProvider>
        <Gated />
      </ModulesProvider>,
    );
    const box = await screen.findByTestId('module-notice');
    expect(box).toHaveAttribute('data-state', 'unreachable');
    expect(box).toHaveTextContent('could not reach the API');
    expect(box).not.toHaveTextContent('is not installed in this deployment');
    expect(screen.queryByTestId('real-page')).not.toBeInTheDocument();
  });

  it('keeps the retry button on screen, disabled, while the retry is in flight', async () => {
    // Clicking Try again used to unmount the whole notice: `refresh()` raised
    // `isLoading`, this wrapper returned null on it, and the page went blank
    // until the probe answered -- up to the ten-second timeout -- so the
    // button's own "Checking..." state could never be seen.
    mockGet.mockRejectedValueOnce(new TypeError('Failed to fetch'));
    render(
      <ModulesProvider>
        <Gated greeting="hi" />
      </ModulesProvider>,
    );
    await screen.findByTestId('module-notice-retry');

    let resolveRetry: (info: ModulesInfo) => void = () => undefined;
    mockGet.mockImplementationOnce(
      () =>
        new Promise<ModulesInfo>((resolve) => {
          resolveRetry = resolve;
        }),
    );
    await userEvent.click(screen.getByTestId('module-notice-retry'));

    const button = screen.getByTestId('module-notice-retry');
    expect(button).toBeInTheDocument();
    expect(button).toBeDisabled();
    expect(button).toHaveTextContent('Checking');
    expect(screen.getByTestId('module-notice')).toHaveAttribute('data-state', 'unreachable');

    await act(async () => {
      resolveRetry(full());
    });
    await waitFor(() => expect(screen.getByTestId('real-page')).toHaveTextContent('hi'));
  });

  it('retries on demand and renders the page once the API answers', async () => {
    mockGet.mockRejectedValueOnce(new TypeError('Failed to fetch'));
    render(
      <ModulesProvider>
        <Gated greeting="hi" />
      </ModulesProvider>,
    );
    await screen.findByTestId('module-notice-retry');

    mockGet.mockResolvedValue(full());
    await userEvent.click(screen.getByTestId('module-notice-retry'));

    await waitFor(() => expect(screen.getByTestId('real-page')).toHaveTextContent('hi'));
    expect(screen.queryByTestId('module-notice')).not.toBeInTheDocument();
  });
});
