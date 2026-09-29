/**
 * What `/experiments/new` does when the create request fails, in both views.
 *
 * Unlike the other two page tests this one does NOT mock `apiFetch`: the real
 * API client runs against a stubbed `fetch`, inside the real `AuthProvider`
 * and `RequireAuth`, because the 401 behaviour is the client's (it clears the
 * token and would send the browser to /login) and the page must survive it.
 */
import React from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import NewExperimentPage, { ROLE_CANNOT_CREATE, SESSION_EXPIRED_CREATE } from '@/pages/experiments/new';
import { AuthProvider } from '@/contexts/AuthContext';
import { RequireAuth } from '@/components/RequireAuth';
import { navigation, TOKEN_STORAGE_KEY, UserMe } from '@/services/api';
import { STEP_HEADINGS } from '@/components/experiments/new/Wizard';
import { makeRouter } from './helpers/apiMock';

let mockRouter = makeRouter();
jest.mock('next/router', () => ({ useRouter: () => mockRouter }));

jest.mock('next/head', () => {
  const Head = ({ children }: { children: React.ReactNode }) => <>{children}</>;
  Head.displayName = 'MockHead';
  return Head;
});

const DEVELOPER: UserMe = {
  id: 'u-2',
  email: 'dev@demo.com',
  username: 'dev',
  full_name: 'Demo Developer',
  role: 'DEVELOPER',
  is_superuser: false,
  is_active: true,
  auth_provider: 'local',
};

const CREATED = { id: 'exp-9', status: 'draft' };

interface Reply {
  status: number;
  body?: unknown;
  requestId?: string;
}

function response({ status, body, requestId }: Reply): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: 'STATUS',
    headers: {
      get: (name: string) => {
        const lower = name.toLowerCase();
        if (lower === 'content-type') return 'application/json';
        if (lower === 'x-request-id') return requestId ?? null;
        return null;
      },
    },
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(body === undefined ? '' : JSON.stringify(body)),
  } as unknown as Response;
}

const mockFetch = jest.fn();
let createReplies: Reply[] = [];

/** `/auth/me` answers the developer while a token is stored; the create answers `createReplies` in turn. */
function stubApi() {
  mockFetch.mockImplementation(async (url: string, init: RequestInit = {}) => {
    const path = new URL(url, 'http://localhost').pathname;
    const method = (init.method ?? 'GET').toUpperCase();
    if (path === '/api/v1/auth/me') {
      const authed = !!(init.headers as Record<string, string> | undefined)?.Authorization;
      return response(authed ? { status: 200, body: DEVELOPER } : { status: 401, body: { detail: 'Not authenticated' } });
    }
    if (path === '/api/v1/experiments' && method === 'POST') {
      const next = createReplies.shift();
      if (!next) throw new Error('unexpected create');
      return response(next);
    }
    throw new Error(`No stub for ${method} ${path}`);
  });
}

const creates = () =>
  mockFetch.mock.calls.filter(
    ([url, init]) =>
      new URL(url as string, 'http://localhost').pathname === '/api/v1/experiments' &&
      ((init as RequestInit | undefined)?.method ?? 'GET').toUpperCase() === 'POST',
  );

let assignSpy: jest.SpyInstance;

beforeEach(() => {
  global.fetch = mockFetch as unknown as typeof fetch;
  mockFetch.mockReset();
  createReplies = [];
  stubApi();
  localStorage.clear();
  localStorage.setItem(TOKEN_STORAGE_KEY, 'token-1');
  assignSpy = jest.spyOn(navigation, 'assign').mockImplementation(() => {});
});

afterEach(() => {
  assignSpy.mockRestore();
});

type View = 'guided' | 'advanced';

function routerFor(view: View) {
  mockRouter = makeRouter({
    pathname: '/experiments/new',
    asPath: view === 'advanced' ? '/experiments/new?advanced' : '/experiments/new',
    query: view === 'advanced' ? { advanced: '' } : {},
  });
}

const setValue = (testId: string, value: string) =>
  fireEvent.change(screen.getByTestId(testId), { target: { value } });

/** Render the page as the app does, fill it in, and press Create. */
async function fillAndCreate(view: View) {
  routerFor(view);
  render(
    <AuthProvider>
      <RequireAuth>
        <NewExperimentPage />
      </RequireAuth>
    </AuthProvider>,
  );
  if (view === 'guided') {
    fireEvent.click(await screen.findByTestId('wizard-next'));
    setValue('experiment-name', 'Checkout redesign');
    setValue('experiment-key', 'checkout_v2');
    fireEvent.click(screen.getByTestId('wizard-next'));
    fireEvent.click(screen.getByTestId('wizard-next'));
    fireEvent.click(screen.getByTestId('wizard-next'));
    expect(screen.getByTestId('wizard-step-heading')).toHaveTextContent(STEP_HEADINGS.review);
  } else {
    await screen.findByTestId('new-experiment-form');
    setValue('experiment-name', 'Checkout redesign');
    setValue('experiment-key', 'checkout_v2');
  }
  pressCreate(view);
}

function pressCreate(view: View) {
  fireEvent.click(screen.getByTestId(view === 'guided' ? 'wizard-create' : 'submit-experiment'));
}

/** The answers are still on screen (Review in guided setup, the fields in the form). */
function expectAnswersKept(view: View) {
  if (view === 'guided') {
    expect(screen.getByTestId('review-name')).toHaveTextContent('Checkout redesign');
    expect(screen.getByTestId('review-key')).toHaveTextContent('checkout_v2');
  } else {
    expect(screen.getByTestId('experiment-name')).toHaveValue('Checkout redesign');
    expect(screen.getByTestId('experiment-key')).toHaveValue('checkout_v2');
  }
}

describe.each<View>(['guided', 'advanced'])('%s: a create that fails', (view) => {
  it('with 401 stays on the page with the answers and the session copy, and does not go to the login page', async () => {
    createReplies = [{ status: 401, body: { detail: 'Could not validate credentials' } }];
    await fillAndCreate(view);

    expect(await screen.findByTestId('form-error')).toHaveTextContent(SESSION_EXPIRED_CREATE);
    expect(creates()).toHaveLength(1);
    expect(assignSpy).not.toHaveBeenCalled();
    expect(mockRouter.replace).not.toHaveBeenCalledWith(expect.stringContaining('/login'));
    expect(mockRouter.push).not.toHaveBeenCalledWith(expect.stringMatching(/^\/(experiments\/exp|login)/));
    expectAnswersKept(view);
    // The API client dropped the rejected token; RequireAuth still shows the page.
    expect(localStorage.getItem(TOKEN_STORAGE_KEY)).toBeNull();
    expect(screen.queryByTestId('require-auth-loading')).not.toBeInTheDocument();
  });

  it('with 401, then signing in again in another tab, creates on the next press', async () => {
    createReplies = [{ status: 401, body: { detail: 'Could not validate credentials' } }, { status: 201, body: CREATED }];
    await fillAndCreate(view);
    await screen.findByTestId('form-error');

    // Another tab signs in: the token is back in shared storage.
    act(() => {
      localStorage.setItem(TOKEN_STORAGE_KEY, 'token-2');
      window.dispatchEvent(new StorageEvent('storage', { key: TOKEN_STORAGE_KEY }));
    });
    pressCreate(view);

    await waitFor(() => expect(mockRouter.push).toHaveBeenCalledWith('/experiments/exp-9'));
    expect(creates()).toHaveLength(2);
    const [, second] = creates()[1] as [string, RequestInit];
    expect((second.headers as Record<string, string>).Authorization).toBe('Bearer token-2');
    expect(assignSpy).not.toHaveBeenCalled();
  });

  it('with 409 says the key is taken in the page’s words, never the API’s, and offers Edit details', async () => {
    // Whatever the 409 body says, the page does not show it: this one is
    // deliberately text the page must never print.
    createReplies = [{ status: 409, body: { detail: 'RAW-409-DETAIL [SQL: INSERT INTO experiments]' } }];
    await fillAndCreate(view);

    const error = await screen.findByTestId('form-error');
    expect(error).toHaveTextContent('An experiment with the key “checkout_v2” already exists.');
    expect(error).toHaveTextContent('Choose a different key');
    expect(error).not.toHaveTextContent('RAW-409-DETAIL');
    expect(document.body).not.toHaveTextContent('[SQL:');
    expectAnswersKept(view);

    fireEvent.click(screen.getByTestId('form-error-edit-details'));
    if (view === 'guided') {
      expect(screen.getByTestId('wizard-step-heading')).toHaveTextContent(STEP_HEADINGS.details);
      expect(mockRouter.push).toHaveBeenCalledWith(
        { pathname: '/experiments/new', query: { step: 'details' } },
        undefined,
        { shallow: true },
      );
    }
    expect(screen.getByTestId('experiment-key')).toHaveFocus();
    expect(screen.getByTestId('experiment-key')).toHaveValue('checkout_v2');
  });

  it('with 409 maps on the status alone: the same text with 400 is shown as the API wrote it', async () => {
    createReplies = [{ status: 400, body: { detail: 'An experiment with the key checkout_v2 is odd' } }];
    await fillAndCreate(view);

    const error = await screen.findByTestId('form-error');
    expect(error).toHaveTextContent('An experiment with the key checkout_v2 is odd');
    expect(screen.queryByTestId('form-error-edit-details')).not.toBeInTheDocument();
  });

  it('with 403 gives the API’s reason and what the role means', async () => {
    createReplies = [{ status: 403, body: { detail: "You don't have permission to create experiments" } }];
    await fillAndCreate(view);

    const error = await screen.findByTestId('form-error');
    expect(error).toHaveTextContent(`You don't have permission to create experiments. ${ROLE_CANNOT_CREATE}`);
    expect(screen.queryByTestId('form-error-edit-details')).not.toBeInTheDocument();
    expect(assignSpy).not.toHaveBeenCalled();
    expectAnswersKept(view);
  });

  it('with 500 shows the API’s message and its request ID once', async () => {
    createReplies = [
      {
        status: 500,
        body: { detail: 'Could not create the experiment. Request ID: req-abc123.' },
        requestId: 'req-abc123',
      },
    ];
    await fillAndCreate(view);

    const error = await screen.findByTestId('form-error');
    expect(error.textContent?.match(/req-abc123/g)).toHaveLength(1);
    expectAnswersKept(view);
  });
});
