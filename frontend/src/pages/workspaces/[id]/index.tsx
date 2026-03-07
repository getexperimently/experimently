import React, { useState, useEffect } from 'react';
import Head from 'next/head';
import Link from 'next/link';
import { useRouter } from 'next/router';
import { Workspace, workspaceService } from '@/services/workspaces';

const PLAN_BADGE: Record<Workspace['plan'], { label: string; className: string }> = {
  free: { label: 'Free', className: 'bg-gray-100 text-gray-700' },
  pro: { label: 'Pro', className: 'bg-blue-100 text-blue-700' },
  enterprise: { label: 'Enterprise', className: 'bg-purple-100 text-purple-700' },
};

interface UsageBarProps {
  label: string;
  used: number;
  max: number;
  href: string;
  colorClass?: string;
}

function UsageBar({ label, used, max, href, colorClass = 'bg-blue-500' }: UsageBarProps) {
  const pct = max > 0 ? Math.min((used / max) * 100, 100) : 0;
  const isWarning = pct >= 80;
  const barColor = isWarning ? 'bg-amber-500' : colorClass;

  return (
    <Link
      href={href}
      className="block bg-white border border-slate-200 rounded-xl p-5 hover:border-blue-300 hover:shadow-sm transition-all group"
    >
      <div className="flex items-center justify-between mb-2">
        <span className="text-sm font-medium text-slate-700">{label}</span>
        <span className="text-sm text-slate-500">
          <span className={`font-semibold ${isWarning ? 'text-amber-600' : 'text-slate-800'}`}>
            {used}
          </span>
          {' '}/ {max}
        </span>
      </div>
      <div className="w-full bg-slate-100 rounded-full h-2">
        <div
          className={`h-2 rounded-full transition-all ${barColor}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      {isWarning && (
        <p className="mt-1.5 text-xs text-amber-600">Approaching limit</p>
      )}
    </Link>
  );
}

interface StatCardProps {
  label: string;
  value: number | string;
  href: string;
  icon: React.ReactNode;
}

function StatCard({ label, value, href, icon }: StatCardProps) {
  return (
    <Link
      href={href}
      className="block bg-white border border-slate-200 rounded-xl p-5 hover:border-blue-300 hover:shadow-sm transition-all group"
    >
      <div className="flex items-center justify-between">
        <div>
          <p className="text-xs text-slate-500 mb-1">{label}</p>
          <p className="text-2xl font-bold text-slate-900">{value}</p>
        </div>
        <div className="w-10 h-10 bg-blue-50 rounded-lg flex items-center justify-center text-blue-600 group-hover:bg-blue-100 transition-colors">
          {icon}
        </div>
      </div>
    </Link>
  );
}

interface EditModalProps {
  workspace: Workspace;
  onClose: () => void;
  onUpdated: (ws: Workspace) => void;
}

function EditWorkspaceModal({ workspace, onClose, onUpdated }: EditModalProps) {
  const [name, setName] = useState(workspace.name);
  const [description, setDescription] = useState(workspace.description ?? '');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const updated = await workspaceService.update(workspace.id, { name, description });
      onUpdated(updated);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to update workspace');
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-md p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-slate-900">Edit Workspace</h2>
          <button
            onClick={onClose}
            className="text-slate-400 hover:text-slate-600 text-xl leading-none"
            aria-label="Close"
          >
            &times;
          </button>
        </div>

        {error && (
          <div className="mb-4 rounded-lg bg-red-50 border border-red-200 p-3 text-sm text-red-700">
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">
              Name <span className="text-red-500">*</span>
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
              className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">
              Slug
            </label>
            <input
              type="text"
              value={workspace.slug}
              disabled
              className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm bg-slate-50 text-slate-400 font-mono cursor-not-allowed"
            />
            <p className="mt-1 text-xs text-slate-400">Slug cannot be changed after creation</p>
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">
              Description
            </label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={3}
              className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
            />
          </div>
          <div className="flex justify-end gap-3 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 text-sm font-medium text-slate-700 bg-white border border-slate-300 rounded-lg hover:bg-slate-50 transition-colors"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={submitting}
              className="px-4 py-2 text-sm font-medium text-white bg-blue-600 rounded-lg hover:bg-blue-700 disabled:opacity-50 transition-colors"
            >
              {submitting ? 'Saving...' : 'Save Changes'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

export default function WorkspaceOverviewPage() {
  const router = useRouter();
  const { id } = router.query as { id: string };
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showEdit, setShowEdit] = useState(false);

  useEffect(() => {
    if (!id) return;
    workspaceService
      .get(id)
      .then(setWorkspace)
      .catch((err) =>
        setError(err instanceof Error ? err.message : 'Failed to load workspace')
      )
      .finally(() => setIsLoading(false));
  }, [id]);

  if (isLoading) {
    return (
      <div className="min-h-screen bg-slate-50 flex items-center justify-center">
        <div className="inline-block w-6 h-6 border-2 border-blue-600 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  if (error || !workspace) {
    return (
      <div className="min-h-screen bg-slate-50 flex items-center justify-center">
        <div className="text-center">
          <p className="text-red-600 mb-4">{error ?? 'Workspace not found'}</p>
          <Link href="/workspaces" className="text-blue-600 hover:underline text-sm">
            Back to Workspaces
          </Link>
        </div>
      </div>
    );
  }

  const badge = PLAN_BADGE[workspace.plan] ?? PLAN_BADGE.free;
  const wsId = workspace.id;

  return (
    <>
      <Head>
        <title>{workspace.name} — Experimently</title>
      </Head>

      <div className="min-h-screen bg-slate-50">
        {/* Nav */}
        <nav className="bg-white border-b border-slate-200 px-6 h-14 flex items-center gap-6">
          <Link href="/" className="text-lg font-semibold text-slate-900">
            Experimently
          </Link>
          <div className="flex items-center gap-4 text-sm">
            <Link href="/experiments" className="text-slate-600 hover:text-slate-900">Experiments</Link>
            <Link href="/feature-flags" className="text-slate-600 hover:text-slate-900">Feature Flags</Link>
            <Link href="/workspaces" className="text-slate-600 hover:text-slate-900">Workspaces</Link>
          </div>
        </nav>

        <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
          {/* Breadcrumb */}
          <div className="flex items-center gap-2 text-sm text-slate-500 mb-6">
            <Link href="/workspaces" className="hover:text-blue-600 transition-colors">
              Workspaces
            </Link>
            <span>/</span>
            <span className="text-slate-900 font-medium">{workspace.name}</span>
          </div>

          {/* Header */}
          <div className="bg-white border border-slate-200 rounded-xl p-6 mb-6">
            <div className="flex items-start justify-between">
              <div className="flex-1">
                <div className="flex items-center gap-3 mb-1">
                  <h1 className="text-2xl font-bold text-slate-900">{workspace.name}</h1>
                  <span
                    className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${badge.className}`}
                  >
                    {badge.label}
                  </span>
                  {!workspace.is_active && (
                    <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-red-100 text-red-700">
                      Inactive
                    </span>
                  )}
                </div>
                <p className="text-sm text-slate-400 font-mono mb-2">{workspace.slug}</p>
                {workspace.description && (
                  <p className="text-sm text-slate-600">{workspace.description}</p>
                )}
              </div>
              <button
                onClick={() => setShowEdit(true)}
                className="ml-4 px-3 py-1.5 text-sm font-medium text-slate-700 bg-white border border-slate-300 rounded-lg hover:bg-slate-50 transition-colors"
              >
                Edit
              </button>
            </div>
          </div>

          {/* Quick links */}
          <div className="flex gap-3 mb-6 flex-wrap">
            <Link
              href={`/workspaces/${wsId}/members`}
              className="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium text-blue-700 bg-blue-50 border border-blue-200 rounded-lg hover:bg-blue-100 transition-colors"
            >
              Manage Members
            </Link>
            <Link
              href={`/workspaces/${wsId}/api-keys`}
              className="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium text-blue-700 bg-blue-50 border border-blue-200 rounded-lg hover:bg-blue-100 transition-colors"
            >
              API Keys
            </Link>
          </div>

          {/* Stats grid */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-6">
            <StatCard
              label="Members"
              value={workspace.member_count ?? 0}
              href={`/workspaces/${wsId}/members`}
              icon={
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z" />
                </svg>
              }
            />
            <StatCard
              label="Experiments"
              value={workspace.experiment_count ?? 0}
              href={`/experiments`}
              icon={
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
                </svg>
              }
            />
            <StatCard
              label="Feature Flags"
              value={workspace.feature_flag_count ?? 0}
              href={`/feature-flags`}
              icon={
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 21v-4m0 0V5a2 2 0 012-2h6.5l1 1H21l-3 6 3 6h-8.5l-1-1H5a2 2 0 00-2 2zm9-13.5V9" />
                </svg>
              }
            />
            <StatCard
              label="API Keys"
              value={workspace.api_key_count ?? 0}
              href={`/workspaces/${wsId}/api-keys`}
              icon={
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 7a2 2 0 012 2m4 0a6 6 0 01-7.743 5.743L11 17H9v2H7v2H4a1 1 0 01-1-1v-2.586a1 1 0 01.293-.707l5.964-5.964A6 6 0 1121 9z" />
                </svg>
              }
            />
          </div>

          {/* Usage / limits */}
          <div className="mb-2">
            <h2 className="text-sm font-semibold text-slate-700 mb-3">Usage &amp; Limits</h2>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
              <UsageBar
                label="Members"
                used={workspace.member_count ?? 0}
                max={workspace.max_members}
                href={`/workspaces/${wsId}/members`}
              />
              <UsageBar
                label="Experiments"
                used={workspace.experiment_count ?? 0}
                max={workspace.max_experiments}
                href={`/experiments`}
                colorClass="bg-green-500"
              />
              <UsageBar
                label="Feature Flags"
                used={workspace.feature_flag_count ?? 0}
                max={workspace.max_feature_flags}
                href={`/feature-flags`}
                colorClass="bg-purple-500"
              />
            </div>
          </div>
        </div>
      </div>

      {showEdit && workspace && (
        <EditWorkspaceModal
          workspace={workspace}
          onClose={() => setShowEdit(false)}
          onUpdated={(updated) => {
            setWorkspace(updated);
            setShowEdit(false);
          }}
        />
      )}
    </>
  );
}
