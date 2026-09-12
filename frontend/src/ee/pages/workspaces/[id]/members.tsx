import React, { useState, useEffect, useRef } from 'react';
import { withFeature } from '@/components/EnterpriseFeatureNotice';
import { FEATURES } from '@/services/edition';
import { PageTitle } from '@/components/PageTitle';
import Link from 'next/link';
import { useRouter } from 'next/router';
import { Workspace, WorkspaceMember, workspaceService } from '@/services/workspaces';

const ROLE_BADGE: Record<WorkspaceMember['role'], { label: string; className: string }> = {
  OWNER: { label: 'Owner', className: 'bg-purple-100 text-purple-700' },
  ADMIN: { label: 'Admin', className: 'bg-red-100 text-red-700' },
  DEVELOPER: { label: 'Developer', className: 'bg-blue-100 text-blue-700' },
  ANALYST: { label: 'Analyst', className: 'bg-green-100 text-green-700' },
  VIEWER: { label: 'Viewer', className: 'bg-gray-100 text-gray-600' },
};

const ROLES: WorkspaceMember['role'][] = ['OWNER', 'ADMIN', 'DEVELOPER', 'ANALYST', 'VIEWER'];

function getInitials(username: string): string {
  return username.slice(0, 2).toUpperCase();
}

interface InviteModalProps {
  workspaceId: string;
  onClose: () => void;
  onInvited: () => void;
}

function InviteModal({ workspaceId, onClose, onInvited }: InviteModalProps) {
  const [email, setEmail] = useState('');
  const [role, setRole] = useState<WorkspaceMember['role']>('DEVELOPER');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await workspaceService.sendInvite(workspaceId, email, role);
      setSuccess(true);
      setTimeout(() => {
        onInvited();
      }, 1500);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to send invite');
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-md p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-slate-900">Invite Member</h2>
          <button
            onClick={onClose}
            className="text-slate-400 hover:text-slate-600 text-xl leading-none"
            aria-label="Close"
          >
            &times;
          </button>
        </div>

        {success && (
          <div className="mb-4 rounded-lg bg-green-50 border border-green-200 p-3 text-sm text-green-700">
            Invitation sent successfully!
          </div>
        )}

        {error && (
          <div className="mb-4 rounded-lg bg-red-50 border border-red-200 p-3 text-sm text-red-700">
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">
              Email Address <span className="text-red-500">*</span>
            </label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              disabled={success}
              className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:bg-slate-50"
              placeholder="colleague@example.com"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">
              Role <span className="text-red-500">*</span>
            </label>
            <select
              value={role}
              onChange={(e) => setRole(e.target.value as WorkspaceMember['role'])}
              disabled={success}
              className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:bg-slate-50"
            >
              {ROLES.filter((r) => r !== 'OWNER').map((r) => (
                <option key={r} value={r}>
                  {ROLE_BADGE[r].label}
                </option>
              ))}
            </select>
            <p className="mt-1 text-xs text-slate-400">
              Owner role can only be transferred, not assigned via invite.
            </p>
          </div>
          <div className="flex justify-end gap-3 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 text-sm font-medium text-slate-700 bg-white border border-slate-300 rounded-lg hover:bg-slate-50 transition-colors"
            >
              {success ? 'Close' : 'Cancel'}
            </button>
            {!success && (
              <button
                type="submit"
                disabled={submitting}
                className="px-4 py-2 text-sm font-medium text-white bg-blue-600 rounded-lg hover:bg-blue-700 disabled:opacity-50 transition-colors"
              >
                {submitting ? 'Sending...' : 'Send Invite'}
              </button>
            )}
          </div>
        </form>
      </div>
    </div>
  );
}

interface RemoveConfirmProps {
  member: WorkspaceMember;
  onConfirm: () => void;
  onCancel: () => void;
  removing: boolean;
}

function RemoveConfirmDialog({ member, onConfirm, onCancel, removing }: RemoveConfirmProps) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-sm p-6">
        <h2 className="text-lg font-semibold text-slate-900 mb-2">Remove Member</h2>
        <p className="text-sm text-slate-600 mb-5">
          Are you sure you want to remove{' '}
          <span className="font-medium">{member.username}</span> from this workspace?
        </p>
        <div className="flex justify-end gap-3">
          <button
            onClick={onCancel}
            className="px-4 py-2 text-sm font-medium text-slate-700 bg-white border border-slate-300 rounded-lg hover:bg-slate-50 transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={onConfirm}
            disabled={removing}
            className="px-4 py-2 text-sm font-medium text-white bg-red-600 rounded-lg hover:bg-red-700 disabled:opacity-50 transition-colors"
          >
            {removing ? 'Removing...' : 'Remove'}
          </button>
        </div>
      </div>
    </div>
  );
}

function WorkspaceMembersPage() {
  const router = useRouter();
  const { id } = router.query as { id: string };
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [members, setMembers] = useState<WorkspaceMember[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showInvite, setShowInvite] = useState(false);
  const [removeTarget, setRemoveTarget] = useState<WorkspaceMember | null>(null);
  const [removing, setRemoving] = useState(false);
  const [updatingRole, setUpdatingRole] = useState<string | null>(null);
  const tooltipRef = useRef<Record<string, boolean>>({});

  async function loadData() {
    if (!id) return;
    try {
      const [ws, mems] = await Promise.all([
        workspaceService.get(id),
        workspaceService.listMembers(id),
      ]);
      setWorkspace(ws);
      setMembers(mems);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load data');
    } finally {
      setIsLoading(false);
    }
  }

  useEffect(() => {
    loadData();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  async function handleRoleChange(member: WorkspaceMember, newRole: WorkspaceMember['role']) {
    if (!id) return;
    setUpdatingRole(member.user_id);
    try {
      const updated = await workspaceService.updateMember(id, member.user_id, newRole);
      setMembers((ms) => ms.map((m) => (m.user_id === member.user_id ? updated : m)));
    } catch (err) {
      alert(err instanceof Error ? err.message : 'Failed to update role');
    } finally {
      setUpdatingRole(null);
    }
  }

  async function handleRemove() {
    if (!id || !removeTarget) return;
    setRemoving(true);
    try {
      await workspaceService.removeMember(id, removeTarget.user_id);
      setMembers((ms) => ms.filter((m) => m.user_id !== removeTarget.user_id));
      setRemoveTarget(null);
    } catch (err) {
      alert(err instanceof Error ? err.message : 'Failed to remove member');
    } finally {
      setRemoving(false);
    }
  }

  const ownerCount = members.filter((m) => m.role === 'OWNER').length;

  if (isLoading) {
    return (
      <div className="flex-1 bg-slate-50 flex items-center justify-center">
        <div className="inline-block w-6 h-6 border-2 border-blue-600 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex-1 bg-slate-50 flex items-center justify-center">
        <p className="text-red-600">{error}</p>
      </div>
    );
  }

  return (
    <>
      <PageTitle title={`Members · ${workspace?.name ?? 'Workspace'}`} />

      <div className="flex-1 bg-slate-50">
        {/* Nav */}

        <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
          {/* Breadcrumb */}
          <div className="flex items-center gap-2 text-sm text-slate-500 mb-6">
            <Link href="/workspaces" className="hover:text-blue-600">Workspaces</Link>
            <span>/</span>
            <Link href={`/workspaces/${id}`} className="hover:text-blue-600">
              {workspace?.name}
            </Link>
            <span>/</span>
            <span className="text-slate-900 font-medium">Members</span>
          </div>

          {/* Header */}
          <div className="flex items-center justify-between mb-6">
            <div>
              <h1 className="text-2xl font-bold text-slate-900">Members</h1>
              <p className="text-sm text-slate-500 mt-1">
                {members.length} member{members.length !== 1 ? 's' : ''} in this workspace
              </p>
            </div>
            <button
              onClick={() => setShowInvite(true)}
              className="inline-flex items-center gap-2 px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 transition-colors"
            >
              + Invite Member
            </button>
          </div>

          {/* Members table */}
          <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 border-b border-slate-200">
                <tr>
                  <th className="text-left px-4 py-3 text-slate-600 font-medium">Member</th>
                  <th className="text-left px-4 py-3 text-slate-600 font-medium">Role</th>
                  <th className="text-left px-4 py-3 text-slate-600 font-medium">Joined</th>
                  <th className="text-right px-4 py-3 text-slate-600 font-medium">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {members.length === 0 && (
                  <tr>
                    <td colSpan={4} className="text-center py-10 text-slate-400">
                      No members yet. Invite someone to get started.
                    </td>
                  </tr>
                )}
                {members.map((member) => {
                  const badge = ROLE_BADGE[member.role];
                  const isLastOwner = member.role === 'OWNER' && ownerCount === 1;
                  const isRoleUpdating = updatingRole === member.user_id;
                  void tooltipRef;

                  return (
                    <tr key={member.user_id} className="hover:bg-slate-50 transition-colors">
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-3">
                          <div className="w-8 h-8 rounded-full bg-blue-100 text-blue-700 flex items-center justify-center text-xs font-semibold flex-shrink-0">
                            {getInitials(member.username)}
                          </div>
                          <div>
                            <p className="font-medium text-slate-900">{member.username}</p>
                            <p className="text-xs text-slate-400">{member.email}</p>
                          </div>
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        {member.role === 'OWNER' ? (
                          <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${badge.className}`}>
                            {badge.label}
                          </span>
                        ) : (
                          <select
                            value={member.role}
                            onChange={(e) =>
                              handleRoleChange(member, e.target.value as WorkspaceMember['role'])
                            }
                            disabled={isRoleUpdating}
                            className="border border-slate-200 rounded-md px-2 py-1 text-xs text-slate-700 focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-50"
                          >
                            {ROLES.filter((r) => r !== 'OWNER').map((r) => (
                              <option key={r} value={r}>
                                {ROLE_BADGE[r].label}
                              </option>
                            ))}
                          </select>
                        )}
                        {isRoleUpdating && (
                          <span className="ml-2 inline-block w-3 h-3 border border-blue-600 border-t-transparent rounded-full animate-spin" />
                        )}
                      </td>
                      <td className="px-4 py-3 text-slate-500 text-xs">
                        {new Date(member.joined_at).toLocaleDateString()}
                      </td>
                      <td className="px-4 py-3 text-right">
                        <div className="relative inline-block">
                          <button
                            onClick={() => !isLastOwner && setRemoveTarget(member)}
                            disabled={isLastOwner}
                            title={
                              isLastOwner
                                ? 'Cannot remove the last owner of a workspace'
                                : `Remove ${member.username}`
                            }
                            className={`text-xs font-medium px-2.5 py-1 rounded-md border transition-colors ${
                              isLastOwner
                                ? 'border-slate-200 text-slate-300 cursor-not-allowed'
                                : 'border-red-200 text-red-600 hover:bg-red-50'
                            }`}
                          >
                            Remove
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      {showInvite && id && (
        <InviteModal
          workspaceId={id}
          onClose={() => setShowInvite(false)}
          onInvited={() => {
            setShowInvite(false);
            loadData();
          }}
        />
      )}

      {removeTarget && (
        <RemoveConfirmDialog
          member={removeTarget}
          onConfirm={handleRemove}
          onCancel={() => setRemoveTarget(null)}
          removing={removing}
        />
      )}
    </>
  );
}

export default withFeature(WorkspaceMembersPage, {
  title: 'Workspace members',
  feature: FEATURES.WORKSPACES,
  description: 'Manage who belongs to a workspace and what role they hold in it.',
});
