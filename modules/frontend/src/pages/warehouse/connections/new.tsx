/**
 * New warehouse connection (ADMIN). Only connectors this deployment has
 * enabled can be chosen; with none enabled there is no form at all.
 */
import React, { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/router';
import { withModule } from '@/components/ModuleNotice';
import { PageTitle } from '@/components/PageTitle';
import { useAuth } from '@/contexts/AuthContext';
import { Connection, ConnectionCreated, Connector, warehouseService } from '@modules/services/warehouse';
import { can, refusal } from '@modules/services/warehouseRoles';
import {
  LoadError,
  Loading,
  NO_CONNECTOR_TEXT,
  RoleNotice,
  WAREHOUSE_MODULE_NOTICE,
  WarehouseHeader,
  errorText,
} from '@modules/components/warehouse/common';
import { ConnectionForm } from '@modules/components/warehouse/ConnectionForm';
import { KeyStatement } from '@modules/components/warehouse/KeyStatement';

function NewConnectionPage() {
  const { user } = useAuth();
  const router = useRouter();
  const allowed = can(user, 'createConnection');
  const [connectors, setConnectors] = useState<Connector[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [created, setCreated] = useState<ConnectionCreated | null>(null);

  const load = useCallback(async () => {
    setError(null);
    setConnectors(null);
    try {
      setConnectors(await warehouseService.listConnectors());
    } catch (err) {
      setError(errorText(err, 'The list of connectors could not be loaded.'));
    }
  }, []);

  useEffect(() => {
    if (allowed) void load();
  }, [allowed, load]);

  const onSaved = (saved: ConnectionCreated | Connection) => {
    const withKey = saved as ConnectionCreated;
    if (withKey.public_key) {
      // Snowflake: the statement that registers the generated key is shown now.
      setCreated(withKey);
      return;
    }
    void router.push(`/warehouse/connections/${saved.id}`);
  };

  const enabled = connectors?.some((c) => c.enabled) ?? false;
  let body: React.ReactNode;
  if (!allowed) body = <RoleNotice message={refusal(user, 'createConnection')} />;
  else if (error) body = <LoadError message={error} onRetry={() => void load()} />;
  else if (!connectors) body = <Loading label="Loading connectors…" />;
  else if (created?.public_key) {
    body = (
      <div className="space-y-4">
        <p role="status" className="text-sm text-slate-800">
          Connection “{created.name}” saved.
        </p>
        <KeyStatement statement={created.public_key} heading="Register the key in Snowflake" />
        <Link href={`/warehouse/connections/${created.id}`} className="text-sm font-medium text-blue-700 underline">
          Go to the connection to test it
        </Link>
      </div>
    );
  } else if (!enabled) {
    body = (
      <p data-testid="warehouse-no-connector" className="text-sm text-slate-700">
        {NO_CONNECTOR_TEXT}
      </p>
    );
  } else {
    body = (
      <ConnectionForm
        mode="create"
        connectors={connectors}
        onSaved={onSaved}
        onCancel={() => void router.push('/warehouse')}
      />
    );
  }

  return (
    <div className="mx-auto max-w-3xl p-6">
      <PageTitle title="New warehouse connection" />
      <WarehouseHeader
        title="New connection"
        crumbs={[{ label: 'Warehouse', href: '/warehouse' }, { label: 'New connection' }]}
      />
      {body}
    </div>
  );
}

export default withModule(NewConnectionPage, WAREHOUSE_MODULE_NOTICE);
