/**
 * Minimal `next/router` stand-in for jest (mapped in jest.config.js). Tests mutate
 * `mockRouter.query` / `mockRouter.pathname` and assert on `mockRouter.push`.
 */
export const mockRouter = {
  pathname: '/',
  route: '/',
  asPath: '/',
  basePath: '',
  query: {} as Record<string, string | string[] | undefined>,
  isReady: true,
  isFallback: false,
  isPreview: false,
  isLocaleDomain: false,
  push: jest.fn(async () => true),
  replace: jest.fn(async () => true),
  prefetch: jest.fn(async () => undefined),
  back: jest.fn(),
  forward: jest.fn(),
  reload: jest.fn(),
  beforePopState: jest.fn(),
  events: { on: jest.fn(), off: jest.fn(), emit: jest.fn() },
};

export function __resetRouter(): void {
  mockRouter.pathname = '/';
  mockRouter.route = '/';
  mockRouter.asPath = '/';
  mockRouter.query = {};
  mockRouter.push.mockClear();
  mockRouter.replace.mockClear();
  mockRouter.prefetch.mockClear();
}

export function useRouter() {
  return mockRouter;
}

const nextRouterMock = { useRouter };
export default nextRouterMock;
