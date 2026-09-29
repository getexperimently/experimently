/**
 * New assignment or metric source (`?kind=assignment|metric`). Assignment
 * sources are ADMIN/DEVELOPER; metric sources also ANALYST (D25).
 */
import React, { useCallback, useEffect, useState } from 'react';
import { useRouter } from 'next/router';
import { withModule } from '@/components/ModuleNotice';
import { PageTitle } from '@/components/PageTitle';
import { useAuth } from '@/contexts/AuthContext';
import { Connection, SourceKind, warehouseService } from '@modules/services/warehouse';
import { can, refusal, sourceAction } from '@modules/services/warehouseRoles';
import {
  LoadError,
  Loading,
  RoleNotice,
  WAREHOUSE_MODULE_NOTICE,
  WarehouseHeader,
  errorText,
} from '@modules/components/warehouse/common';
import { SourceForm } from '@modules/components/warehouse/SourceForm';

function NewSourcePage() {
  const { user } = useAuth();
  const router = useRouter();
  const kind: SourceKind = router.query.kind === 'metric' ? 'metric' : 'assignment';
  const connectionId = typeof router.query.connection === 'string' ? router.query.connection : null;
  const allowed = can(user, sourceAction('create', kind));
  const [connections, setConnections] = useState<Connection[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const title = kind === 'assignment' ? 'New assignment source' : 'New metric source';

  const load = useCallback(async () => {
    setError(null);
    setConnections(null);
    try {
      setConnections(await warehouseService.listConnections());
    } catch (err) {
      setError(errorText(err, 'The warehouse connections could not be loaded.'));
    }
  }, []);

  useEffect(() => {
    if (router.isReady && allowed) void load();
  }, [router.isReady, allowed, load]);

  let body: React.ReactNode;
  if (!router.isReady) body = <Loading label="Loading…" />;
  else if (!allowed) body = <RoleNotice message={refusal(user, sourceAction('create', kind))} />;
  else if (error) body = <LoadError message={error} onRetry={() => void load()} />;
  else if (!connections) body = <Loading label="Loading warehouse connections…" />;
  else if (connections.length === 0) {
    body = (
      <p className="text-sm text-slate-700" data-testid="warehouse-source-needs-connection">
        A source reads a table through a warehouse connection, and there are no connections yet.
        {can(user, 'createConnection') ? ' Create one first.' : ' An admin can create one.'}
      </p>
    );
  } else {
    body = (
      <SourceForm
        mode="create"
        kind={kind}
        connections={connections}
        connectionId={connectionId}
        onSaved={(source) => void router.push(`/warehouse/sources/${source.id}`)}
        onCancel={() => void router.push(`/warehouse?tab=${kind}`)}
      />
    );
  }

  return (
    <div className="mx-auto max-w-3xl p-6">
      <PageTitle title={title} />
      <WarehouseHeader
        title={title}
        crumbs={[{ label: 'Warehouse', href: `/warehouse?tab=${kind}` }, { label: title }]}
      />
      {body}
    </div>
  );
}

export default withModule(NewSourcePage, WAREHOUSE_MODULE_NOTICE);
