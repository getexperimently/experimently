import React, { useState, useEffect } from 'react';
import { withFeature } from '@/components/EnterpriseFeatureNotice';
import { FEATURES } from '@/services/edition';
import { PageTitle } from '@/components/PageTitle';
import Link from 'next/link';
import { useRouter } from 'next/router';
import { WorkspaceInvite, workspaceService } from '@/services/workspaces';

function isTokenExpired(invite: WorkspaceInvite): boolean {
  return new Date(invite.expires_at) < new Date();
}

function AcceptInvitePage() {
  const router = useRouter();
  const { token } = router.query as { token: string };

  const [invite, setInvite] = useState<WorkspaceInvite | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const [accepting, setAccepting] = useState(false);
  const [acceptError, setAcceptError] = useState<string | null>(null);
  const [accepted, setAccepted] = useState(false);

  useEffect(() => {
    if (!token) return;

    // Authentication is enforced by <RequireAuth> in _app.tsx (this route is
    // protected), which redirects anonymous visitors to /login?next=<this page>.
    workspaceService
      .getInvite(token)
      .then(setInvite)
      .catch((err) => {
        const msg = err instanceof Error ? err.message : 'Failed to load invite';
        setFetchError(msg);
      })
      .finally(() => setIsLoading(false));
  }, [token, router]);

  async function handleAccept() {
    if (!token) return;
    setAccepting(true);
    setAcceptError(null);
    try {
      const result = await workspaceService.acceptInvite(token);
      setAccepted(true);
      setTimeout(() => {
        router.push(`/workspaces/${result.workspace_id}`);
      }, 1500);
    } catch (err) {
      setAcceptError(err instanceof Error ? err.message : 'Failed to accept invitation');
    } finally {
      setAccepting(false);
    }
  }

  return (
    <>
      <PageTitle title="Accept Invitation" />

      <div className="flex-1 bg-slate-50 flex flex-col">
        {/* Simple header */}

        <div className="flex-1 flex items-center justify-center px-4 py-12">
          <div className="w-full max-w-md">
            {/* Loading */}
            {isLoading && (
              <div className="bg-white rounded-xl border border-slate-200 p-10 text-center">
                <div className="inline-block w-8 h-8 border-2 border-blue-600 border-t-transparent rounded-full animate-spin mb-4" />
                <p className="text-slate-500 text-sm">Loading invitation...</p>
              </div>
            )}

            {/* Fetch error */}
            {!isLoading && fetchError && (
              <div className="bg-white rounded-xl border border-red-200 p-8 text-center">
                <div className="w-14 h-14 bg-red-100 rounded-full flex items-center justify-center mx-auto mb-4">
                  <svg className="w-7 h-7 text-red-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                  </svg>
                </div>
                <h2 className="text-lg font-semibold text-slate-900 mb-2">Invitation Not Found</h2>
                <p className="text-sm text-slate-500 mb-6">
                  This invitation link is invalid or has already been used.
                </p>
                <Link
                  href="/workspaces"
                  className="inline-flex items-center gap-2 px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 transition-colors"
                >
                  Go to Workspaces
                </Link>
              </div>
            )}

            {/* Expired invite */}
            {!isLoading && !fetchError && invite && isTokenExpired(invite) && (
              <div className="bg-white rounded-xl border border-amber-200 p-8 text-center">
                <div className="w-14 h-14 bg-amber-100 rounded-full flex items-center justify-center mx-auto mb-4">
                  <svg className="w-7 h-7 text-amber-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
                  </svg>
                </div>
                <h2 className="text-lg font-semibold text-slate-900 mb-2">Invitation Expired</h2>
                <p className="text-sm text-slate-500 mb-2">
                  This invitation to{' '}
                  <span className="font-medium">{invite.workspace_name}</span> has expired.
                </p>
                <p className="text-xs text-slate-400 mb-6">
                  Expired on {new Date(invite.expires_at).toLocaleDateString()}
                </p>
                <p className="text-sm text-slate-500 mb-6">
                  Please ask a workspace admin to send you a new invitation.
                </p>
                <Link
                  href="/workspaces"
                  className="inline-flex items-center gap-2 px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 transition-colors"
                >
                  Go to Workspaces
                </Link>
              </div>
            )}

            {/* Valid invite */}
            {!isLoading && !fetchError && invite && !isTokenExpired(invite) && (
              <div className="bg-white rounded-xl border border-slate-200 p-8 text-center">
                {accepted ? (
                  <>
                    <div className="w-14 h-14 bg-green-100 rounded-full flex items-center justify-center mx-auto mb-4">
                      <svg className="w-7 h-7 text-green-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                      </svg>
                    </div>
                    <h2 className="text-lg font-semibold text-slate-900 mb-2">
                      Invitation Accepted!
                    </h2>
                    <p className="text-sm text-slate-500">
                      Redirecting you to the workspace...
                    </p>
                  </>
                ) : (
                  <>
                    <div className="w-14 h-14 bg-blue-100 rounded-full flex items-center justify-center mx-auto mb-4">
                      <svg className="w-7 h-7 text-blue-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4" />
                      </svg>
                    </div>

                    <h2 className="text-xl font-bold text-slate-900 mb-1">
                      You&apos;re invited!
                    </h2>
                    <p className="text-sm text-slate-500 mb-5">
                      <span className="font-medium">{invite.inviter_username}</span> has invited you
                      to join the workspace{' '}
                      <span className="font-medium text-slate-800">{invite.workspace_name}</span> as{' '}
                      <span className="font-medium">{invite.role}</span>.
                    </p>

                    <div className="bg-slate-50 rounded-lg p-3 mb-5 text-sm text-slate-600">
                      <span className="block text-xs text-slate-400 mb-1">Invitation for</span>
                      <span className="font-medium">{invite.email}</span>
                    </div>

                    {acceptError && (
                      <div className="mb-4 rounded-lg bg-red-50 border border-red-200 p-3 text-sm text-red-700">
                        {acceptError}
                      </div>
                    )}

                    <button
                      onClick={handleAccept}
                      disabled={accepting}
                      className="w-full px-4 py-2.5 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                    >
                      {accepting ? 'Accepting...' : 'Accept Invitation'}
                    </button>

                    <p className="mt-3 text-xs text-slate-400">
                      Invitation expires {new Date(invite.expires_at).toLocaleDateString()}
                    </p>
                  </>
                )}
              </div>
            )}
          </div>
        </div>
      </div>
    </>
  );
}

export default withFeature(AcceptInvitePage, {
  title: 'Workspace invitations',
  feature: FEATURES.WORKSPACES,
  description: 'Accept an invitation to join a workspace.',
});
