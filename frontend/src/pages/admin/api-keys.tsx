import React, { useState } from 'react';
import { AdminLayout } from '@/components/admin/AdminLayout';
import { ApiKeyTable } from '@/components/admin/api-keys/ApiKeyTable';
import { CreateApiKeyModal } from '@/components/admin/api-keys/CreateApiKeyModal';

export function ApiKeysPage() {
  const [modalOpen, setModalOpen] = useState(false);
  const [newKeyBanner, setNewKeyBanner] = useState<string | null>(null);
  const [tableKey, setTableKey] = useState(0);

  const handleKeyCreated = (keyValue: string) => {
    setNewKeyBanner(keyValue);
    setModalOpen(false);
    // Re-mount the table to trigger a fresh fetch
    setTableKey((prev) => prev + 1);
  };

  return (
    <AdminLayout title="API Keys" currentPath="/admin/api-keys">
      <div data-testid="api-keys-page" className="flex flex-col gap-5">
        <h2 className="text-xl font-semibold text-slate-900">API Keys</h2>

        {/* Banner showing the newly created key (shown once) */}
        {newKeyBanner && (
          <div
            data-testid="new-key-banner"
            className="p-4 bg-amber-50 border border-amber-300 rounded-md flex items-center justify-between"
          >
            <div>
              <p className="text-sm font-semibold text-amber-800">
                Copy this key — it won&apos;t be shown again
              </p>
              <p className="font-mono text-sm text-amber-900 mt-1">
                {newKeyBanner.slice(0, 8)}...
              </p>
            </div>
            <button
              data-testid="dismiss-key-banner"
              onClick={() => setNewKeyBanner(null)}
              className="text-amber-600 hover:text-amber-800 text-sm font-medium ml-4"
            >
              Dismiss
            </button>
          </div>
        )}

        <ApiKeyTable
          key={tableKey}
          onCreateKey={() => setModalOpen(true)}
        />

        <CreateApiKeyModal
          isOpen={modalOpen}
          onClose={() => setModalOpen(false)}
          onSuccess={handleKeyCreated}
        />
      </div>
    </AdminLayout>
  );
}

export default ApiKeysPage;
