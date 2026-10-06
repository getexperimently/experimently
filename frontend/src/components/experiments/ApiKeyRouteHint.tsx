import React from 'react';
import { docsUrl } from '@/services/docs';

/**
 * The route any signed-in user may call to create an API key for themselves,
 * as the docs name it (docs/workspaces/overview.md, "API Keys"). The
 * dashboard's own page for keys, /admin/api-keys, opens only for a superuser
 * (withAdminGuard), so everyone else is pointed here instead (#920).
 */
export const API_KEY_ROUTE = 'POST /api/v1/api-keys';

/**
 * One sentence telling a reader who cannot open Admin → API Keys how to get a
 * key. Inline, so it can end a sentence of the caller's own.
 */
export function ApiKeyRouteHint({ testId }: { testId: string }) {
  return (
    <span data-testid={testId}>
      Create one for yourself with <code className="font-mono">{API_KEY_ROUTE}</code> (see{' '}
      <a href={docsUrl('security/api-keys')} className="text-blue-600 hover:underline">
        API Key Management
      </a>
      ) or ask an administrator.
    </span>
  );
}
