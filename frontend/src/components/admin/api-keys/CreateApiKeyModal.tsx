import React, { useState } from 'react';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

interface CreatedApiKey {
  id: string;
  name: string;
  key_value: string;
  prefix: string;
  created_at: string;
  is_active: boolean;
}

interface CreateApiKeyModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess: (keyValue: string) => void;
}

const SCOPES = ['read', 'write', 'admin'] as const;
type Scope = typeof SCOPES[number];

export function CreateApiKeyModal({ isOpen, onClose, onSuccess }: CreateApiKeyModalProps) {
  const [name, setName] = useState('');
  const [scope, setScope] = useState<Scope>('read');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [createdKey, setCreatedKey] = useState<CreatedApiKey | null>(null);

  if (!isOpen) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;

    setSubmitting(true);
    setError(null);

    try {
      const response = await fetch(`${API_URL}/api/v1/api-keys`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: name.trim(), scope }),
      });

      if (!response.ok) {
        throw new Error(`Failed to create API key: ${response.statusText}`);
      }

      const data: CreatedApiKey = await response.json();
      setCreatedKey(data);
      onSuccess(data.key_value);
    } catch (err) {
      setError((err as Error).message || 'Failed to create API key');
    } finally {
      setSubmitting(false);
    }
  };

  const handleClose = () => {
    setName('');
    setScope('read');
    setError(null);
    setCreatedKey(null);
    onClose();
  };

  const maskedKeyDisplay = createdKey
    ? `${createdKey.key_value.slice(0, 8)}...`
    : null;

  return (
    <div
      data-testid="create-api-key-modal"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black bg-opacity-40"
      role="dialog"
      aria-modal="true"
    >
      <div className="bg-white rounded-xl shadow-xl w-full max-w-md mx-4 p-6">
        <h2 className="text-lg font-semibold text-slate-900 mb-4">
          {createdKey ? 'API Key Created' : 'Create API Key'}
        </h2>

        {/* Key revealed state */}
        {createdKey ? (
          <div>
            <p className="text-sm text-slate-600 mb-3">
              Copy this key now — it will not be shown again.
            </p>
            <div className="bg-slate-50 border border-slate-200 rounded-md p-3 flex items-center justify-between mb-4">
              <span
                data-testid="masked-key-value"
                className="font-mono text-sm text-slate-800"
              >
                {maskedKeyDisplay}
              </span>
              <button
                data-testid="copy-key-button"
                onClick={() => navigator.clipboard.writeText(createdKey.key_value)}
                className="ml-3 text-xs text-blue-600 hover:text-blue-800 font-medium"
              >
                Copy
              </button>
            </div>
            <div className="flex justify-end">
              <button
                data-testid="modal-done-button"
                onClick={handleClose}
                className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-md hover:bg-blue-700"
              >
                Done
              </button>
            </div>
          </div>
        ) : (
          /* Creation form */
          <form onSubmit={handleSubmit} noValidate>
            {/* Name */}
            <div className="mb-4">
              <label
                htmlFor="api-key-name"
                className="block text-sm font-medium text-slate-700 mb-1"
              >
                Name <span className="text-red-500">*</span>
              </label>
              <input
                id="api-key-name"
                data-testid="api-key-name-input"
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g. Production Key"
                className="w-full px-3 py-2 border border-slate-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>

            {/* Scope */}
            <div className="mb-4">
              <label
                htmlFor="api-key-scope"
                className="block text-sm font-medium text-slate-700 mb-1"
              >
                Permission Scope
              </label>
              <select
                id="api-key-scope"
                data-testid="api-key-scope-input"
                value={scope}
                onChange={(e) => setScope(e.target.value as Scope)}
                className="w-full px-3 py-2 border border-slate-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                {SCOPES.map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </select>
            </div>

            {/* Error */}
            {error && (
              <div
                data-testid="modal-error"
                className="mb-4 text-sm text-red-600 bg-red-50 border border-red-200 rounded-md p-3"
              >
                {error}
              </div>
            )}

            {/* Actions */}
            <div className="flex justify-end gap-3">
              <button
                type="button"
                data-testid="modal-cancel-button"
                onClick={handleClose}
                className="px-4 py-2 text-sm font-medium text-slate-700 border border-slate-300 rounded-md hover:bg-slate-50"
              >
                Cancel
              </button>
              <button
                type="submit"
                data-testid="create-api-key-submit"
                disabled={!name.trim() || submitting}
                className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-md hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {submitting ? 'Creating...' : 'Create Key'}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
