/**
 * "Warehouse analysis (beta)" on the experiment page: start an analysis of
 * this experiment in the customer's own warehouse, follow it, read its
 * results, and see the SQL it ran.
 *
 * Renders nothing unless the `warehouse` module is installed on this
 * instance. In a core build the `@modules/*` alias resolves this file to a
 * stub that renders nothing at all.
 *
 * Roles (the API's matrix): every role reads runs and results; ADMIN and
 * DEVELOPER start runs; ADMIN, DEVELOPER and ANALYST see the SQL a run sent.
 * Others see why they cannot, in text. A View SQL button needs both the
 * `viewRunSql` capability and statements in the response, which the API sends
 * as null to the other roles.
 *
 * Accessibility: the latest run's status is announced from a polite live
 * region (`role="status"`); a refused start is `role="alert"` because it is
 * the failure of an action the user just took; a failed run already on the
 * page is not an alert. No state is shown by colour alone.
 */
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useAuth } from '@/contexts/AuthContext';
import { useModule } from '@/contexts/ModulesContext';
import { isApiError } from '@/services/api';
import { MODULES } from '@/services/modules';
import {
  BETA_EXPLANATION,
  RUN_POLL_MS,
  STATUS_TEXT,
  WarehouseRun,
  canStartRun,
  effectiveRole,
  failureCopy,
  utcText,
  warehouseName,
  warehouseRunsService,
} from '@modules/services/warehouseRuns';
import { can, refusal } from '@modules/services/warehouseRoles';
import RunResults from '@modules/components/warehouse/runs/RunResults';
import StartRunForm from '@modules/components/warehouse/runs/StartRunForm';
import ViewSqlDialog from '@modules/components/warehouse/runs/ViewSqlDialog';

export interface WarehouseExperiment {
  id: string;
  key: string | null;
  start_date?: string | null;
}

export interface WarehouseAnalysisSectionProps {
  experiment: WarehouseExperiment;
}

const IN_FLIGHT = new Set(['queued', 'running']);

function BetaChip() {
  const [open, setOpen] = useState(false);
  return (
    <span className="relative inline-flex">
      <button
        type="button"
        aria-expanded={open}
        aria-controls="warehouse-beta-explanation"
        onClick={() => setOpen((v) => !v)}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={() => setOpen(false)}
        className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-semibold text-amber-800"
        data-testid="warehouse-beta"
      >
        Beta
      </button>
      <span
        id="warehouse-beta-explanation"
        role="note"
        hidden={!open}
        className="absolute left-0 top-full z-10 mt-1 w-72 rounded-md border border-slate-200 bg-white p-2 text-xs font-normal text-slate-700 shadow"
      >
        {BETA_EXPLANATION}
      </span>
    </span>
  );
}

function statusSentence(run: WarehouseRun): string {
  const where = `${warehouseName(run.warehouse_type)} · ${run.connection_name}`;
  switch (run.status) {
    case 'queued':
      return `Analysis queued on ${where}. It starts when the warehouse has capacity.`;
    case 'running':
      return `Analysis running on ${where}. This page updates when it finishes.`;
    case 'succeeded':
      return `Analysis succeeded at ${utcText(run.finished_at)}.`;
    case 'failed':
    default:
      return `Analysis failed at ${utcText(run.finished_at)}.`;
  }
}

export default function WarehouseAnalysisSection({ experiment }: WarehouseAnalysisSectionProps) {
  const installed = useModule(MODULES.WAREHOUSE);
  const { user } = useAuth();
  const [runs, setRuns] = useState<WarehouseRun[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [latest, setLatest] = useState<WarehouseRun | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [sqlFor, setSqlFor] = useState<{ run: WarehouseRun; trigger: HTMLElement } | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const experimentId = experiment.id;
  const experimentKey = experiment.key ?? 'this experiment';
  const mayStart = canStartRun(user);
  const maySeeSql = can(user, 'viewRunSql');

  const load = useCallback(async () => {
    try {
      const body = await warehouseRunsService.listRuns(experimentId);
      const list = body?.runs ?? [];
      setRuns(list);
      setLatest(list[0] ?? null);
      setLoadError(null);
    } catch (err) {
      setRuns([]);
      setLoadError(
        isApiError(err) && err.isForbidden
          ? err.message
          : `Could not load warehouse analyses: ${err instanceof Error ? err.message : 'unknown error'}`,
      );
    }
  }, [experimentId]);

  useEffect(() => {
    if (installed) void load();
  }, [installed, load]);

  // Poll the latest run while it is queued or running.
  const latestId = latest?.id;
  const latestInFlight = latest ? IN_FLIGHT.has(latest.status) : false;
  useEffect(() => {
    if (!latestId || !latestInFlight) return undefined;
    let active = true;
    const tick = async () => {
      try {
        const run = await warehouseRunsService.getRun(latestId);
        if (!active) return;
        setLatest(run);
        setRuns((current) =>
          current ? current.map((r) => (r.id === run.id ? run : r)) : current,
        );
        if (IN_FLIGHT.has(run.status)) timer.current = setTimeout(tick, RUN_POLL_MS);
      } catch {
        if (active) timer.current = setTimeout(tick, RUN_POLL_MS * 2);
      }
    };
    timer.current = setTimeout(tick, RUN_POLL_MS);
    return () => {
      active = false;
      if (timer.current) clearTimeout(timer.current);
    };
  }, [latestId, latestInFlight]);

  const onStarted = async (runId: string) => {
    setShowForm(false);
    try {
      const run = await warehouseRunsService.getRun(runId);
      setLatest(run);
      setRuns((current) => [run, ...(current ?? []).filter((r) => r.id !== run.id)]);
    } catch {
      await load();
    }
  };

  if (!installed) return null;

  const lastGood = (runs ?? []).find((r) => r.status === 'succeeded' && r.results) ?? null;
  const shownFailure = latest && latest.status === 'failed' ? latest : null;
  const role = effectiveRole(user);

  return (
    <section
      className="mt-6 rounded-lg border border-slate-200 bg-white"
      aria-labelledby="warehouse-analysis-title"
      data-testid="warehouse-analysis"
    >
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 px-5 py-4">
        <div className="flex items-center gap-2">
          <h2 id="warehouse-analysis-title" className="text-base font-semibold text-slate-800">
            Warehouse analysis
          </h2>
          <BetaChip />
        </div>
        {mayStart && !showForm && (
          <button
            type="button"
            onClick={() => setShowForm(true)}
            disabled={latestInFlight}
            aria-describedby={latestInFlight ? 'warehouse-in-flight-note' : undefined}
            className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50"
            data-testid="warehouse-open-form"
          >
            Analyse in warehouse
          </button>
        )}
      </div>

      <div className="space-y-4 px-5 py-4">
        <p className="text-sm text-slate-600">
          Runs this experiment’s analysis in your own warehouse, on your exposure and metric
          tables. Only aggregates come back.
        </p>
        {!mayStart && (
          <p className="text-sm text-slate-700" data-testid="warehouse-role-note">
            Starting a warehouse analysis requires the ADMIN or DEVELOPER role; you are{' '}
            {role ?? 'signed in without a role'}. You can read every analysis below.
          </p>
        )}
        {!maySeeSql && (
          <p className="text-sm text-slate-700" data-testid="warehouse-sql-note">
            {refusal(user, 'viewRunSql')}
          </p>
        )}
        {latestInFlight && mayStart && !showForm && (
          <p id="warehouse-in-flight-note" className="text-sm text-slate-600">
            An analysis is in progress; you can start another when it finishes.
          </p>
        )}

        {mayStart && showForm && (
          <div className="rounded-md border border-slate-200 p-4">
            <StartRunForm
              experimentId={experimentId}
              hasStartDate={!!experiment.start_date}
              onStarted={(id) => void onStarted(id)}
            />
            <button
              type="button"
              onClick={() => setShowForm(false)}
              className="mt-3 text-sm font-medium text-slate-700 underline"
              data-testid="warehouse-close-form"
            >
              Cancel
            </button>
          </div>
        )}

        <div role="status" aria-live="polite" data-testid="warehouse-run-status">
          {latest ? (
            <p className="text-sm text-slate-800" data-status={latest.status}>
              <span className="font-medium">{STATUS_TEXT[latest.status] ?? latest.status}:</span>{' '}
              {statusSentence(latest)}
            </p>
          ) : null}
        </div>

        {loadError && (
          <p className="text-sm text-slate-800" data-testid="warehouse-load-error">
            {loadError}
          </p>
        )}

        {runs !== null && runs.length === 0 && !loadError && (
          <p className="text-sm text-slate-600" data-testid="warehouse-no-runs">
            No warehouse analysis of this experiment yet.
          </p>
        )}

        {shownFailure && (
          <div
            className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-900"
            data-testid="warehouse-run-failed"
            data-code={shownFailure.error_code ?? ''}
          >
            {(() => {
              const copy = failureCopy(shownFailure.error_code, shownFailure.error_message, {
                warehouse: warehouseName(shownFailure.warehouse_type),
                connection: shownFailure.connection_name,
                experimentKey,
              });
              return (
                <>
                  <p className="font-medium">Failed: {copy.title}</p>
                  {copy.fix && <p className="mt-1">{copy.fix}</p>}
                  <p className="mt-1 text-xs">
                    Run {shownFailure.id}
                    {shownFailure.error_code ? ` · code ${shownFailure.error_code}` : ''}
                  </p>
                </>
              );
            })()}
            {maySeeSql && shownFailure.statements && shownFailure.statements.length > 0 && (
              <button
                type="button"
                onClick={(e) => setSqlFor({ run: shownFailure, trigger: e.currentTarget })}
                className="mt-2 text-sm font-medium text-blue-700 underline"
                data-testid="warehouse-failed-view-sql"
              >
                View SQL
              </button>
            )}
          </div>
        )}

        {lastGood && lastGood.results && (
          <div>
            {latest && lastGood.id !== latest.id && (
              <p className="mb-2 text-sm text-slate-700" data-testid="warehouse-results-dated">
                These results are from the analysis that finished{' '}
                <time dateTime={lastGood.finished_at ?? undefined}>{utcText(lastGood.finished_at)}</time>.
              </p>
            )}
            <RunResults
              run={lastGood}
              results={lastGood.results}
              experimentKey={experimentKey}
              onViewSql={maySeeSql ? (trigger) => setSqlFor({ run: lastGood, trigger }) : undefined}
            />
          </div>
        )}

        {runs && runs.length > 1 && (
          <details data-testid="warehouse-run-history">
            <summary className="cursor-pointer text-sm font-medium text-slate-800">
              Run history ({runs.length})
            </summary>
            <table className="mt-2 w-full text-sm">
              <caption className="sr-only">Warehouse analyses of this experiment, newest first</caption>
              <thead>
                <tr className="text-left text-slate-700">
                  <th scope="col" className="py-1 pr-4 font-medium">Started</th>
                  <th scope="col" className="py-1 pr-4 font-medium">Status</th>
                  <th scope="col" className="py-1 pr-4 font-medium">Connection</th>
                  <th scope="col" className="py-1 font-medium">Code</th>
                </tr>
              </thead>
              <tbody>
                {runs.map((r) => (
                  <tr key={r.id} data-testid="warehouse-history-row">
                    <td className="py-1 pr-4">
                      <time dateTime={r.created_at ?? undefined}>{utcText(r.created_at)}</time>
                    </td>
                    <td className="py-1 pr-4">{STATUS_TEXT[r.status] ?? r.status}</td>
                    <td className="py-1 pr-4">{r.connection_name}</td>
                    <td className="py-1">{r.error_code ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </details>
        )}
      </div>

      {maySeeSql && sqlFor && sqlFor.run.statements && (
        <ViewSqlDialog
          statements={sqlFor.run.statements}
          returnFocusTo={sqlFor.trigger}
          onClose={() => setSqlFor(null)}
        />
      )}
    </section>
  );
}
