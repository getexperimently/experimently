/**
 * `/workspaces/invites/[token]` (#265): only the account the invite was sent
 * to sees the Accept button. Anyone else sees who it was sent to (masked) and
 * can switch account; a 403 `invite_email_mismatch` from the API shows the
 * same state.
 */
import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { ModulesProvider } from '@/contexts/ModulesContext';
import { ApiError, UserMe } from '@/services/api';
import AcceptInvitePage from '@modules/pages/workspaces/invites/[token]';
import { workspaceService } from '@modules/services/workspaces';

const mockReplace = jest.fn().mockResolvedValue(true);
const mockPush = jest.fn().mockResolvedValue(true);

jest.mock('next/router', () => ({
  useRouter: () => ({
    replace: mockReplace,
    push: mockPush,
    pathname: '/workspaces/invites/[token]',
    asPath: '/workspaces/invites/tok123',
    query: { token: 'tok123' },
    isReady: true,
  }),
}));

jest.mock('next/head', () => {
  const MockHead = ({ children }: { children: React.ReactNode }) => <>{children}</>;
  MockHead.displayName = 'MockHead';
  return MockHead;
});

const mockLogout = jest.fn().mockResolvedValue(undefined);
let mockUser: Partial<UserMe> | null = null;

jest.mock('@/contexts/AuthContext', () => ({
  useOptionalAuth: () => ({ user: mockUser, logout: mockLogout }),
  useAuth: () => ({ user: mockUser, logout: mockLogout }),
}));

jest.mock('@modules/services/workspaces', () => ({
  workspaceService: { getInvite: jest.fn(), acceptInvite: jest.fn() },
}));

const getInvite = workspaceService.getInvite as jest.Mock;
const acceptInvite = workspaceService.acceptInvite as jest.Mock;

const INVITED = 'alice@example.com';
const KELVIN = 'K';

function signedInAs(email: string | null) {
  mockUser = {
    id: 'u-1',
    email: email as string,
    username: 'someone',
    role: 'VIEWER',
    is_superuser: false,
    is_active: true,
  };
}

function renderPage() {
  return render(
    <ModulesProvider initial={{ profile: 'full', modules: ['workspaces'], version: 'test' }}>
      <AcceptInvitePage />
    </ModulesProvider>,
  );
}

beforeEach(() => {
  jest.clearAllMocks();
  getInvite.mockResolvedValue({
    token: 'tok123',
    workspace_name: 'Growth',
    inviter_username: 'owner',
    email: INVITED,
    role: 'DEVELOPER',
    expires_at: new Date(Date.now() + 86_400_000).toISOString(),
  });
});

describe('/workspaces/invites/[token]', () => {
  it('offers Accept to the invited address, whatever its case', async () => {
    signedInAs('  Alice@Example.COM ');
    renderPage();

    expect(await screen.findByRole('button', { name: 'Accept Invitation' })).toBeInTheDocument();
    expect(screen.queryByText('This invitation is for a different account')).not.toBeInTheDocument();
  });

  it.each([
    ['a different address', 'bob@other.com'],
    ['a plus alias of it', 'alice+x@example.com'],
  ])('shows the mismatch state, with no Accept button, to %s', async (_label, email) => {
    signedInAs(email);
    renderPage();

    expect(
      await screen.findByRole('heading', { name: 'This invitation is for a different account' }),
    ).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Accept Invitation' })).not.toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent(
      `It was sent to a•••@example.com, and you are signed in as ${email}. ` +
        `Sign in with the invited address to accept it, or ask a workspace admin to invite ${email}.`,
    );
    expect(document.body.textContent).not.toContain(INVITED);
  });

  it('treats a non-ASCII character that lower-cases to ASCII as a different address', async () => {
    const lookAlike = `${KELVIN}im@example.com`;
    getInvite.mockResolvedValue({
      token: 'tok123',
      workspace_name: 'Growth',
      inviter_username: 'owner',
      email: 'kim@example.com',
      role: 'DEVELOPER',
      expires_at: new Date(Date.now() + 86_400_000).toISOString(),
    });
    expect(lookAlike.toLowerCase()).toBe('kim@example.com');
    signedInAs(lookAlike);
    renderPage();

    expect(
      await screen.findByRole('heading', { name: 'This invitation is for a different account' }),
    ).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Accept Invitation' })).not.toBeInTheDocument();
  });

  it('shows the mismatch state to an account with no email address', async () => {
    signedInAs(null);
    renderPage();

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'It was sent to a•••@example.com, and the account you are signed in with has no email address.',
    );
    expect(screen.queryByRole('button', { name: 'Accept Invitation' })).not.toBeInTheDocument();
  });

  it('"Use a different account" signs out and returns to this link after sign-in', async () => {
    signedInAs('bob@other.com');
    renderPage();

    fireEvent.click(await screen.findByRole('button', { name: 'Use a different account' }));

    await waitFor(() =>
      expect(mockReplace).toHaveBeenCalledWith(
        `/login?next=${encodeURIComponent('/workspaces/invites/tok123')}`,
      ),
    );
    expect(mockLogout).toHaveBeenCalledTimes(1);
    expect(acceptInvite).not.toHaveBeenCalled();
  });

  it('"Use a different account" still returns to sign-in when sign-out fails', async () => {
    signedInAs('bob@other.com');
    mockLogout.mockRejectedValueOnce(new Error('network down'));
    renderPage();

    fireEvent.click(await screen.findByRole('button', { name: 'Use a different account' }));

    await waitFor(() =>
      expect(mockReplace).toHaveBeenCalledWith(
        `/login?next=${encodeURIComponent('/workspaces/invites/tok123')}`,
      ),
    );
  });

  it('shows the mismatch state when the API answers 403 invite_email_mismatch', async () => {
    signedInAs(INVITED);
    acceptInvite.mockRejectedValue(
      new ApiError({
        status: 403,
        detail: {
          code: 'invite_email_mismatch',
          message: 'This invite was sent to a different email address.',
        },
      }),
    );
    renderPage();

    fireEvent.click(await screen.findByRole('button', { name: 'Accept Invitation' }));

    expect(
      await screen.findByRole('heading', { name: 'This invitation is for a different account' }),
    ).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Accept Invitation' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Use a different account' })).toBeInTheDocument();
  });

  it('shows any other accept failure as an alert beside the Accept button', async () => {
    signedInAs(INVITED);
    acceptInvite.mockRejectedValue(
      new ApiError({ status: 409, detail: 'This invite has already been accepted.' }),
    );
    renderPage();

    fireEvent.click(await screen.findByRole('button', { name: 'Accept Invitation' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'This invite has already been accepted.',
    );
    expect(screen.getByRole('button', { name: 'Accept Invitation' })).toBeInTheDocument();
  });
});
