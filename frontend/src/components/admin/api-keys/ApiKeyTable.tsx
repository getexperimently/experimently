import React, { useCallback, useEffect, useState } from 'react';
import { ApiKey } from '@/types/admin';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

interface ApiKeyTableProps {
  onCreateKey: () => void;
}

function formatDate(isoString: string): string {
  try {
    return new Date(isoString).toLocaleString();
  } catch {
    return isoString;
  }
}

export function ApiKeyTable({ onCreateKey }: ApiKeyTableProps) {
  const [keys, setKeys] = useState<ApiKey[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchKeys = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(`${API_URL}/api/v1/api-keys`);
      if (!response.ok) {
        throw new Error(`Failed to fetch API keys: ${response.statusText}`);
      }
      const data: ApiKey[] = await response.json();
      setKeys(data);
    } catch (err) {
      setError((err as Error).message || 'Failed to load API keys');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchKeys();
  }, [fetchKeys]);

  const handleRevoke = async (key: ApiKey) => {
    const confirmed = window.confirm(
      `Are you sure you want to revoke the API key "${key.name}"? This cannot be undone.`
    );
    if (!confirmed) return;

    try {
      const response = await fetch(`${API_URL}/api/v1/api-keys/${key.id}`, {
        method: 'DELETE',
      });
      if (!response.ok) {
        throw new Error(`Failed to revoke API key: ${response.statusText}`);
      }
      await fetchKeys();
    } catch (err) {
      alert(`Failed to revoke API key: ${(err as Error).message}`);
    }
  };

  return (
    <div
      data-testid="api-key-table"
      className="bg-white rounded-lg border border-slate-200 overflow-hidden"
    >
      {/* Toolbar */}
      <div className="flex items-center justify-between p-4 border-b border-slate-200">
        <h2 className="text-sm font-semibold text-slate-900">API Keys</h2>
        <button
          data-testid="create-api-key-button"
          onClick={onCreateKey}
          className="px-3 py-1.5 bg-blue-600 text-white text-sm font-medium rounded-md hover:bg-blue-700 transition-colors"
        >
          Create API Key
        </button>
      </div>

      {/* Loading state */}
      {loading && (
        <div data-testid="api-key-table-loading" className="divide-y divide-slate-100">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="flex items-center gap-4 px-6 py-4 animate-pulse">
              <div className="h-4 bg-slate-200 rounded w-1/4" />
              <div className="h-4 bg-slate-200 rounded w-1/4" />
              <div className="h-4 bg-slate-200 rounded w-1/4" />
              <div className="h-5 bg-slate-200 rounded w-16" />
            </div>
          ))}
        </div>
      )}

      {/* Error state */}
      {!loading && error && (
        <div
          data-testid="api-key-error-state"
          className="p-8 text-center text-red-600"
        >
          <p className="font-medium">Failed to load API keys</p>
          <p className="text-sm mt-1 text-red-500">{error}</p>
        </div>
      )}

      {/* Empty state */}
      {!loading && !error && keys.length === 0 && (
        <div
          data-testid="api-key-empty-state"
          className="p-8 text-center text-slate-500"
        >
          <p>No API keys found. Create one to get started.</p>
        </div>
      )}

      {/* Table */}
      {!loading && !error && keys.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-slate-600 uppercase text-xs tracking-wide">
              <tr>
                <th className="px-6 py-3 text-left">Name</th>
                <th className="px-6 py-3 text-left">Prefix</th>
                <th className="px-6 py-3 text-left">Created At</th>
                <th className="px-6 py-3 text-left">Status</th>
                <th className="px-6 py-3 text-left">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {keys.map((key) => (
                <tr
                  key={key.id}
                  data-testid={`api-key-row-${key.id}`}
                  className="hover:bg-slate-50"
                >
                  <td className="px-6 py-4 font-medium text-slate-900">{key.name}</td>
                  <td className="px-6 py-4 text-slate-600 font-mono text-xs">{key.prefix}</td>
                  <td
                    data-testid={`created-at-${key.id}`}
                    className="px-6 py-4 text-slate-600"
                  >
                    {formatDate(key.created_at)}
                  </td>
                  <td className="px-6 py-4">
                    <span
                      data-testid={`status-badge-${key.id}`}
                      className={[
                        'inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium',
                        key.is_active
                          ? 'bg-green-100 text-green-800'
                          : 'bg-slate-100 text-slate-600',
                      ].join(' ')}
                    >
                      {key.is_active ? 'active' : 'revoked'}
                    </span>
                  </td>
                  <td className="px-6 py-4">
                    {key.is_active && (
                      <button
                        data-testid={`revoke-button-${key.id}`}
                        onClick={() => handleRevoke(key)}
                        className="text-red-600 hover:text-red-800 text-sm font-medium"
                      >
                        Revoke
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
