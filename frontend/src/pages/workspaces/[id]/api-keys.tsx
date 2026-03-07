import React, { useState, useEffect, useCallback } from 'react';
import Head from 'next/head';
import Link from 'next/link';
import { useRouter } from 'next/router';
import {
  Workspace,
  WorkspaceAPIKey,
  CreateWorkspaceAPIKeyResponse,
  workspaceService,
} from '@/services/workspaces';

const AVAILABLE_SCOPES = [
  { value: 'experiments:read', label: 'Experiments — Read' },
  { value: 'experiments:write', label: 'Experiments — Write' },
  { value: 'feature_flags:read', label: 'Feature Flags — Read' },
  { value: 'feature_flags:write', label: 'Feature Flags — Write' },
  { value: 'metrics:read', label: 'Metrics — Read' },
  { value: 'users:read', label: 'Users — Read' },
  { value: 'analytics:read', label: 'Analytics — Read' },
];

interface CreateKeyModalProps {
  workspaceId: string;
  onClose: () => void;
  onCreated: (result: CreateWorkspaceAPIKeyResponse) => void;
}

function CreateKeyModal({ workspaceId, onClose, onCreated }: CreateKeyModalProps) {
  const [name, setName] = useState('');
  const [scopes, setScopes] = useState<string[]>(['experiments:read', 'feature_flags:read']);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function toggleScope(scope: string) {
    setScopes((s) =>
      s.includes(scope) ? s.filter((x) => x !== scope) : [...s, scope]
    );
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (scopes.length === 0) {
      setError('Select at least one scope');
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const result = await workspaceService.createAPIKey(workspaceId, { name, scopes });
      onCreated(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create API key');
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-md p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-slate-900">Create API Key</h2>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-600 text-xl" aria-label="Close">
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
              Key Name <span className="text-red-500">*</span>
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
              className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              placeholder="e.g. Production Backend"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-700 mb-2">
              Scopes <span className="text-red-500">*</span>
            </label>
            <div className="space-y-2 max-h-48 overflow-y-auto border border-slate-200 rounded-lg p-3">
              {AVAILABLE_SCOPES.map((s) => (
                <label key={s.value} className="flex items-center gap-2 cursor-pointer hover:bg-slate-50 rounded p-1">
                  <input
                    type="checkbox"
                    checked={scopes.includes(s.value)}
                    onChange={() => toggleScope(s.value)}
                    className="w-4 h-4 text-blue-600 border-slate-300 rounded focus:ring-blue-500"
                  />
                  <span className="text-sm text-slate-700">{s.label}</span>
                  <span className="ml-auto text-xs text-slate-400 font-mono">{s.value}</span>
                </label>
              ))}
            </div>
            {scopes.length === 0 && (
              <p className="mt-1 text-xs text-red-500">Select at least one scope</p>
            )}
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
              disabled={submitting || scopes.length === 0}
              className="px-4 py-2 text-sm font-medium text-white bg-blue-600 rounded-lg hover:bg-blue-700 disabled:opacity-50 transition-colors"
            >
              {submitting ? 'Creating...' : 'Create Key'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

interface KeyRevealModalProps {
  apiKey: string;
  title: string;
  onClose: () => void;
}

function KeyRevealModal({ apiKey, title, onClose }: KeyRevealModalProps) {
  const [copied, setCopied] = useState(false);

  function handleCopy() {
    navigator.clipboard.writeText(apiKey).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-lg p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-slate-900">{title}</h2>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-600 text-xl" aria-label="Close">
            &times;
          </button>
        </div>

        <div className="mb-4 rounded-lg bg-amber-50 border border-amber-200 p-3">
          <div className="flex items-start gap-2">
            <svg className="w-4 h-4 text-amber-600 mt-0.5 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
            </svg>
            <p className="text-sm text-amber-800">
              <strong>This key will not be shown again.</strong> Copy it now and store it in a secure location.
            </p>
          </div>
        </div>

        <div className="mb-4">
          <div className="flex items-center gap-2 bg-slate-900 rounded-lg p-3 font-mono text-sm text-green-400 overflow-x-auto">
            <span className="flex-1 break-all">{apiKey}</span>
          </div>
        </div>

        <div className="flex justify-end gap-3">
          <button
            onClick={handleCopy}
            className={`px-4 py-2 text-sm font-medium rounded-lg transition-colors ${
              copied
                ? 'bg-green-600 text-white'
                : 'bg-blue-600 text-white hover:bg-blue-700'
            }`}
          >
            {copied ? 'Copied!' : 'Copy to Clipboard'}
          </button>
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm font-medium text-slate-700 bg-white border border-slate-300 rounded-lg hover:bg-slate-50 transition-colors"
          >
            Done
          </button>
        </div>
      </div>
    </div>
  );
}

interface RevokeConfirmProps {
  keyName: string;
  onConfirm: () => void;
  onCancel: () => void;
  revoking: boolean;
}

function RevokeConfirmDialog({ keyName, onConfirm, onCancel, revoking }: RevokeConfirmProps) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-sm p-6">
        <h2 className="text-lg font-semibold text-slate-900 mb-2">Revoke API Key</h2>
        <p className="text-sm text-slate-600 mb-5">
          Are you sure you want to revoke{' '}
          <span className="font-medium">&quot;{keyName}&quot;</span>? This action cannot be undone and
          any integrations using this key will stop working immediately.
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
            disabled={revoking}
            className="px-4 py-2 text-sm font-medium text-white bg-red-600 rounded-lg hover:bg-red-700 disabled:opacity-50 transition-colors"
          >
            {revoking ? 'Revoking...' : 'Revoke Key'}
          </button>
        </div>
      </div>
    </div>
  );
}

export default function WorkspaceAPIKeysPage() {
  const router = useRouter();
  const { id } = router.query as { id: string };
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [apiKeys, setApiKeys] = useState<WorkspaceAPIKey[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [revealedKey, setRevealedKey] = useState<{ key: string; title: string } | null>(null);
  const [revokeTarget, setRevokeTarget] = useState<WorkspaceAPIKey | null>(null);
  const [revoking, setRevoking] = useState(false);
  const [rotatingId, setRotatingId] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    if (!id) return;
    try {
      const [ws, keys] = await Promise.all([
        workspaceService.get(id),
        workspaceService.listAPIKeys(id),
      ]);
      setWorkspace(ws);
      setApiKeys(keys);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load API keys');
    } finally {
      setIsLoading(false);
    }
  }, [id]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  function handleCreated(result: CreateWorkspaceAPIKeyResponse) {
    setShowCreate(false);
    setApiKeys((keys) => [result, ...keys]);
    setRevealedKey({ key: result.key, title: 'API Key Created' });
  }

  async function handleRevoke() {
    if (!id || !revokeTarget) return;
    setRevoking(true);
    try {
      await workspaceService.revokeAPIKey(id, revokeTarget.id);
      setApiKeys((keys) => keys.filter((k) => k.id !== revokeTarget.id));
      setRevokeTarget(null);
    } catch (err) {
      alert(err instanceof Error ? err.message : 'Failed to revoke key');
    } finally {
      setRevoking(false);
    }
  }

  async function handleRotate(key: WorkspaceAPIKey) {
    if (!id) return;
    setRotatingId(key.id);
    try {
      const result = await workspaceService.rotateAPIKey(id, key.id);
      setApiKeys((keys) =>
        keys.map((k) => (k.id === key.id ? result : k))
      );
      setRevealedKey({ key: result.key, title: 'API Key Rotated' });
    } catch (err) {
      alert(err instanceof Error ? err.message : 'Failed to rotate key');
    } finally {
      setRotatingId(null);
    }
  }

  if (isLoading) {
    return (
      <div className="min-h-screen bg-slate-50 flex items-center justify-center">
        <div className="inline-block w-6 h-6 border-2 border-blue-600 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-h-screen bg-slate-50 flex items-center justify-center">
        <p className="text-red-600">{error}</p>
      </div>
    );
  }

  return (
    <>
      <Head>
        <title>API Keys — {workspace?.name ?? 'Workspace'} — Experimently</title>
      </Head>

      <div className="min-h-screen bg-slate-50">
        {/* Nav */}
        <nav className="bg-white border-b border-slate-200 px-6 h-14 flex items-center gap-6">
          <Link href="/" className="text-lg font-semibold text-slate-900">Experimently</Link>
          <div className="flex items-center gap-4 text-sm">
            <Link href="/experiments" className="text-slate-600 hover:text-slate-900">Experiments</Link>
            <Link href="/feature-flags" className="text-slate-600 hover:text-slate-900">Feature Flags</Link>
            <Link href="/workspaces" className="text-slate-600 hover:text-slate-900">Workspaces</Link>
          </div>
        </nav>

        <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
          {/* Breadcrumb */}
          <div className="flex items-center gap-2 text-sm text-slate-500 mb-6">
            <Link href="/workspaces" className="hover:text-blue-600">Workspaces</Link>
            <span>/</span>
            <Link href={`/workspaces/${id}`} className="hover:text-blue-600">
              {workspace?.name}
            </Link>
            <span>/</span>
            <span className="text-slate-900 font-medium">API Keys</span>
          </div>

          {/* Header */}
          <div className="flex items-center justify-between mb-6">
            <div>
              <h1 className="text-2xl font-bold text-slate-900">API Keys</h1>
              <p className="text-sm text-slate-500 mt-1">
                Manage API keys for programmatic access to this workspace
              </p>
            </div>
            <button
              onClick={() => setShowCreate(true)}
              className="inline-flex items-center gap-2 px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 transition-colors"
            >
              + Create API Key
            </button>
          </div>

          {/* Keys table */}
          {apiKeys.length === 0 ? (
            <div className="text-center py-16 bg-white rounded-xl border border-slate-200">
              <div className="w-14 h-14 bg-slate-100 rounded-full flex items-center justify-center mx-auto mb-4">
                <svg className="w-7 h-7 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 7a2 2 0 012 2m4 0a6 6 0 01-7.743 5.743L11 17H9v2H7v2H4a1 1 0 01-1-1v-2.586a1 1 0 01.293-.707l5.964-5.964A6 6 0 1121 9z" />
                </svg>
              </div>
              <h3 className="text-slate-700 font-medium mb-1">No API keys yet</h3>
              <p className="text-slate-400 text-sm mb-5">
                Create an API key to integrate your applications with this workspace
              </p>
              <button
                onClick={() => setShowCreate(true)}
                className="inline-flex items-center gap-2 px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 transition-colors"
              >
                Create your first API key
              </button>
            </div>
          ) : (
            <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
              <table className="w-full text-sm">
                <thead className="bg-slate-50 border-b border-slate-200">
                  <tr>
                    <th className="text-left px-4 py-3 text-slate-600 font-medium">Name</th>
                    <th className="text-left px-4 py-3 text-slate-600 font-medium">Key Prefix</th>
                    <th className="text-left px-4 py-3 text-slate-600 font-medium">Scopes</th>
                    <th className="text-left px-4 py-3 text-slate-600 font-medium">Last Used</th>
                    <th className="text-left px-4 py-3 text-slate-600 font-medium">Created</th>
                    <th className="text-right px-4 py-3 text-slate-600 font-medium">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {apiKeys.map((key) => (
                    <tr key={key.id} className="hover:bg-slate-50 transition-colors">
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2">
                          <span className="font-medium text-slate-900">{key.name}</span>
                          {!key.is_active && (
                            <span className="inline-flex items-center px-1.5 py-0.5 rounded text-xs font-medium bg-red-100 text-red-700">
                              Revoked
                            </span>
                          )}
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        <span className="font-mono text-xs bg-slate-100 text-slate-700 px-2 py-1 rounded">
                          {key.key_prefix}****
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex flex-wrap gap-1">
                          {key.scopes.slice(0, 3).map((scope) => (
                            <span
                              key={scope}
                              className="inline-flex items-center px-1.5 py-0.5 rounded text-xs bg-blue-50 text-blue-700"
                            >
                              {scope}
                            </span>
                          ))}
                          {key.scopes.length > 3 && (
                            <span className="inline-flex items-center px-1.5 py-0.5 rounded text-xs bg-slate-100 text-slate-600">
                              +{key.scopes.length - 3} more
                            </span>
                          )}
                        </div>
                      </td>
                      <td className="px-4 py-3 text-slate-500 text-xs">
                        {key.last_used_at
                          ? new Date(key.last_used_at).toLocaleDateString()
                          : 'Never'}
                      </td>
                      <td className="px-4 py-3 text-slate-500 text-xs">
                        {new Date(key.created_at).toLocaleDateString()}
                      </td>
                      <td className="px-4 py-3 text-right">
                        <div className="flex items-center justify-end gap-2">
                          <button
                            onClick={() => handleRotate(key)}
                            disabled={!key.is_active || rotatingId === key.id}
                            title="Rotate key"
                            className="text-xs font-medium px-2.5 py-1 rounded-md border border-amber-200 text-amber-700 hover:bg-amber-50 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                          >
                            {rotatingId === key.id ? 'Rotating...' : 'Rotate'}
                          </button>
                          <button
                            onClick={() => setRevokeTarget(key)}
                            disabled={!key.is_active}
                            title="Revoke key"
                            className="text-xs font-medium px-2.5 py-1 rounded-md border border-red-200 text-red-600 hover:bg-red-50 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                          >
                            Revoke
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>

      {showCreate && id && (
        <CreateKeyModal
          workspaceId={id}
          onClose={() => setShowCreate(false)}
          onCreated={handleCreated}
        />
      )}

      {revealedKey && (
        <KeyRevealModal
          apiKey={revealedKey.key}
          title={revealedKey.title}
          onClose={() => setRevealedKey(null)}
        />
      )}

      {revokeTarget && (
        <RevokeConfirmDialog
          keyName={revokeTarget.name}
          onConfirm={handleRevoke}
          onCancel={() => setRevokeTarget(null)}
          revoking={revoking}
        />
      )}
    </>
  );
}
