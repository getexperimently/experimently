/**
 * One warehouse connection: its non-secret settings, its credential status,
 * and -- for ADMIN -- edit, test, regenerate the Snowflake key, and delete.
 * The API never returns a stored secret, so there is none to show.
 */
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/router';
import { withModule } from '@/components/ModuleNotice';
import { PageTitle } from '@/components/PageTitle';
import { useAuth } from '@/contexts/AuthContext';
import {
  Connection,
  ConnectionCreated,
  Connector,
  PublicKeyStatement,
  warehouseName,
  warehouseService,
} from '@modules/services/warehouse';
import { can, refusal } from '@modules/services/warehouseRoles';
import {
  BUTTON_DANGER,
  BUTTON_SECONDARY,
  CREDENTIALS_STATUS_TEXT,
  ConfirmDialog,
  CopyBlock,
  LoadError,
  Loading,
  RoleNotice,
  UtcTime,
  WAREHOUSE_MODULE_NOTICE,
  WarehouseHeader,
  errorText,
  notAvailableText,
} from '@modules/components/warehouse/common';
import { ConnectionForm } from '@modules/components/warehouse/ConnectionForm';
import { KeyStatement } from '@modules/components/warehouse/KeyStatement';
import { formatBytes, formatSeconds } from '@modules/components/warehouse/validation';

const PARAMETER_LABELS: Record<string, string> = {
  account: 'Account',
  user: 'User',
  role: 'Role',
  warehouse: 'Warehouse',
  billing_project: 'Billing project',
  location: 'Location',
  client_email: 'Service account',
  region: 'Region',
  role_arn: 'Role ARN',
  workgroup: 'Workgroup',
  database: 'Database',
};

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-3 gap-4 py-2">
      <dt className="text-sm font-medium text-slate-700">{label}</dt>
      <dd className="col-span-2 break-all text-sm text-slate-900">{children}</dd>
    </div>
  );
}

interface TestOutcome {
  ok: boolean;
  message: string;
}

function ConnectionPage() {
  const { user } = useAuth();
  const router = useRouter();
  const id = typeof router.query.id === 'string' ? router.query.id : null;
  const allowed = can(user, 'viewConnections');
  const admin = can(user, 'changeConnection');
  const [connection, setConnection] = useState<Connection | null>(null);
  const [connectors, setConnectors] = useState<Connector[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [testing, setTesting] = useState(false);
  const [outcome, setOutcome] = useState<TestOutcome | null>(null);
  const [pendingKey, setPendingKey] = useState<PublicKeyStatement | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const outcomeRef = useRef<HTMLDivElement>(null);

  const load = useCallback(async () => {
    if (!id) return;
    setError(null);
    setConnection(null);
    try {
      const [found, list] = await Promise.all([
        warehouseService.getConnection(id),
        warehouseService.listConnectors(),
      ]);
      setConnection(found);
      setConnectors(list);
    } catch (err) {
      setError(errorText(err, 'The connection could not be loaded.'));
    }
  }, [id]);

  useEffect(() => {
    if (allowed) void load();
  }, [allowed, load]);

  const test = async () => {
    if (!connection) return;
    setTesting(true);
    setOutcome(null);
    setActionError(null);
    try {
      const result = await warehouseService.testConnection(connection.id);
      const time = new Date().toISOString().slice(11, 16);
      setOutcome({
        ok: true,
        message: `Test passed at ${time} UTC: signed in to ${warehouseName(connection.warehouse_type)} and ran a query that reads no table.${
          result.promoted_pending_key ? ' The new key is now in use.' : ''
        }`,
      });
      if (result.promoted_pending_key) {
        setPendingKey(null);
        setConnection(await warehouseService.getConnection(connection.id));
      }
    } catch (err) {
      setOutcome({ ok: false, message: `Test failed: ${errorText(err, 'the warehouse did not answer.')}` });
    } finally {
      setTesting(false);
      outcomeRef.current?.focus();
    }
  };

  const regenerate = async () => {
    if (!connection) return;
    setActionError(null);
    try {
      const result: ConnectionCreated = await warehouseService.regenerateKey(connection.id);
      setPendingKey(result.public_key);
      const { public_key: _shown, ...rest } = result;
      void _shown;
      setConnection(rest);
    } catch (err) {
      setActionError(errorText(err, 'A new key was not generated.'));
    }
  };

  const remove = async () => {
    if (!connection) return;
    setDeleting(true);
    setDeleteError(null);
    try {
      await warehouseService.deleteConnection(connection.id);
      void router.push('/warehouse');
    } catch (err) {
      setDeleteError(errorText(err, 'The connection was not deleted.'));
      setDeleting(false);
    }
  };

  let body: React.ReactNode;
  if (!allowed) body = <RoleNotice message={refusal(user, 'viewConnections')} />;
  else if (error) body = <LoadError message={error} onRetry={() => void load()} />;
  else if (!connection) body = <Loading label="Loading the connection…" />;
  else if (editing) {
    body = (
      <ConnectionForm
        mode="edit"
        connectors={connectors}
        connection={connection}
        onSaved={(updated) => {
          setConnection(updated);
          setEditing(false);
          setSaved(true);
        }}
        onCancel={() => setEditing(false)}
      />
    );
  } else {
    const c = connection;
    const params = Object.entries(c.parameters).filter(([k]) => PARAMETER_LABELS[k]);
    body = (
      <div className="space-y-6">
        {saved && (
          <p role="status" className="text-sm text-slate-800">
            Changes saved.
          </p>
        )}
        {!c.enabled && (
          <p data-testid="warehouse-connection-unavailable" className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
            {notAvailableText(c)} This connection can&apos;t be tested, changed or used until it is.
          </p>
        )}
        <dl className="divide-y divide-slate-100 rounded-md border border-slate-200 bg-white px-4" data-testid="warehouse-connection-details">
          <Row label="Warehouse">{warehouseName(c.warehouse_type)}</Row>
          {params.map(([k, v]) => (
            <Row key={k} label={PARAMETER_LABELS[k]}>
              {v}
            </Row>
          ))}
          <Row label="Credentials">{CREDENTIALS_STATUS_TEXT[c.credentials_status]}</Row>
          {c.public_key_fingerprint && (
            <Row label="Key fingerprint">
              <code className="font-mono text-xs">{c.public_key_fingerprint}</code>
            </Row>
          )}
          {c.pending_public_key_fingerprint && (
            <Row label="New key fingerprint">
              <code className="font-mono text-xs">{c.pending_public_key_fingerprint}</code> (waiting for a passing test)
            </Row>
          )}
          <Row label="Query time limit">{formatSeconds(c.query_timeout_seconds)}</Row>
          {c.max_bytes_per_query !== null && <Row label="Most data per query">{formatBytes(c.max_bytes_per_query)}</Row>}
          <Row label="Analyses per day">{c.max_runs_per_day} (UTC day, previews included)</Row>
          {c.worst_case_bytes_per_day !== null && (
            <Row label="Most data read per day">{formatBytes(c.worst_case_bytes_per_day)}</Row>
          )}
          {c.worst_case_seconds_per_day !== null && (
            <Row label="Most query time per day">{formatSeconds(c.worst_case_seconds_per_day)}</Row>
          )}
          <Row label="Last changed">
            <UtcTime value={c.updated_at ?? c.created_at} />
          </Row>
        </dl>

        {c.external_id && (
          <section aria-labelledby="wh-external-id" className="space-y-2">
            <h2 id="wh-external-id" className="text-base font-semibold text-slate-900">
              External ID
            </h2>
            <p className="text-sm text-slate-700">Your role&apos;s trust policy must require this external ID.</p>
            <CopyBlock label="external ID" text={c.external_id} />
          </section>
        )}

        {pendingKey && <KeyStatement statement={pendingKey} heading="Register the new key in Snowflake" pending />}

        {admin ? (
          <div className="space-y-3">
            <div className="flex flex-wrap gap-3">
              <button type="button" onClick={() => setEditing(true)} disabled={!c.enabled} className={BUTTON_SECONDARY}>
                Edit
              </button>
              <button type="button" onClick={test} disabled={!c.enabled || testing} className={BUTTON_SECONDARY}>
                {testing ? 'Testing…' : 'Test connection'}
              </button>
              {c.warehouse_type === 'snowflake' && (
                <button type="button" onClick={regenerate} disabled={!c.enabled} className={BUTTON_SECONDARY}>
                  Generate a new key
                </button>
              )}
              <button
                type="button"
                onClick={() => {
                  setDeleteError(null);
                  setConfirmDelete(true);
                }}
                className={BUTTON_DANGER}
              >
                Delete
              </button>
            </div>
            <div
              ref={outcomeRef}
              tabIndex={-1}
              aria-live="polite"
              data-testid="warehouse-connection-test-result"
              className="text-sm focus:outline-none"
            >
              {outcome && <p className={outcome.ok ? 'text-slate-800' : 'text-red-800'}>{outcome.message}</p>}
            </div>
            {actionError && (
              <p role="alert" className="text-sm text-red-800">
                {actionError}
              </p>
            )}
          </div>
        ) : (
          <RoleNotice message={refusal(user, 'changeConnection')} />
        )}

        {confirmDelete && (
          <ConfirmDialog
            title={`Delete “${c.name}”?`}
            confirmLabel="Delete connection"
            busy={deleting}
            error={deleteError}
            onConfirm={remove}
            onCancel={() => setConfirmDelete(false)}
          >
            <p>
              The connection and its stored credentials are deleted, and so are the sources that use it. Past
              analyses keep their results.
            </p>
          </ConfirmDialog>
        )}
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-3xl p-6">
      <PageTitle title={connection ? `${connection.name} · Warehouse` : 'Warehouse connection'} />
      <WarehouseHeader
        title={connection?.name ?? 'Connection'}
        crumbs={[{ label: 'Warehouse', href: '/warehouse' }, { label: connection?.name ?? 'Connection' }]}
      />
      {body}
    </div>
  );
}

export default withModule(ConnectionPage, WAREHOUSE_MODULE_NOTICE);
