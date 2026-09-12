import React, { useState } from 'react';
import Link from 'next/link';
import { apiBase } from '@/services/api';

/** Origin shown in the curl sample: configured API URL, else the page origin. */
export function sampleApiOrigin(): string {
  const base = apiBase();
  if (base) return base;
  if (typeof window !== 'undefined' && window.location) return window.location.origin;
  return 'http://localhost:8000';
}

export function assignCurlSample(origin: string, experimentKey = 'my-first-experiment'): string {
  return [
    `curl -X POST "${origin}/api/v1/tracking/assign" \\`,
    `  -H "X-API-Key: $API_KEY" \\`,
    `  -H "Content-Type: application/json" \\`,
    `  -d '{"experiment_key": "${experimentKey}", "user_id": "user-123"}'`,
  ].join('\n');
}

interface FirstRunChecklistProps {
  /** Key of an existing experiment to use in the sample; defaults to a placeholder. */
  experimentKey?: string;
}

/**
 * Three-step onboarding card shown on `/experiments` when the list is empty:
 * create an experiment → mint an API key → send an assignment with the SDK.
 */
export function FirstRunChecklist({ experimentKey }: FirstRunChecklistProps) {
  const [copied, setCopied] = useState(false);
  const curl = assignCurlSample(sampleApiOrigin(), experimentKey);

  const copy = async () => {
    try {
      await navigator.clipboard?.writeText(curl);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard unavailable — the text is selectable */
    }
  };

  const stepClass = 'flex gap-4';
  const badgeClass =
    'flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-blue-600 text-white text-xs font-semibold';

  return (
    <div
      className="bg-white rounded-lg border border-slate-200 p-6 sm:p-8"
      data-testid="first-run-checklist"
    >
      <h2 className="text-lg font-semibold text-slate-900">Get your first result in three steps</h2>
      <p className="text-sm text-slate-500 mt-1 mb-6">
        Nothing here yet. Here is the shortest path from an empty workspace to a live assignment.
      </p>

      <ol className="space-y-6">
        <li className={stepClass} data-testid="checklist-step-1">
          <span className={badgeClass}>1</span>
          <div className="min-w-0">
            <h3 className="text-sm font-semibold text-slate-800">Create an experiment</h3>
            <p className="text-sm text-slate-500 mt-0.5">
              Give it a name, a control and a treatment variant, and at least one metric.
            </p>
            <Link
              href="/experiments/new"
              className="inline-flex items-center mt-2 px-3 py-1.5 rounded-md bg-blue-600 text-white text-sm font-medium hover:bg-blue-700"
              data-testid="checklist-create-experiment"
            >
              + New Experiment
            </Link>
          </div>
        </li>

        <li className={stepClass} data-testid="checklist-step-2">
          <span className={badgeClass}>2</span>
          <div className="min-w-0">
            <h3 className="text-sm font-semibold text-slate-800">Create an API key</h3>
            <p className="text-sm text-slate-500 mt-0.5">
              SDKs and the tracking API authenticate with <code className="font-mono">X-API-Key</code>.
              Keys are shown once — copy it when it appears.
            </p>
            <Link
              href="/admin/api-keys"
              className="inline-flex items-center mt-2 text-sm font-medium text-blue-600 hover:underline"
              data-testid="checklist-api-keys"
            >
              Open Admin → API Keys &rarr;
            </Link>
          </div>
        </li>

        <li className={stepClass} data-testid="checklist-step-3">
          <span className={badgeClass}>3</span>
          <div className="min-w-0 flex-1">
            <h3 className="text-sm font-semibold text-slate-800">Send an assignment</h3>
            <p className="text-sm text-slate-500 mt-0.5">
              Call the tracking API (or any{' '}
              <Link href="/docs" className="text-blue-600 hover:underline">
                SDK
              </Link>
              ) with your experiment key. The response carries the variant to render.
            </p>
            <div className="relative mt-2">
              <pre
                className="bg-slate-900 text-slate-100 text-xs rounded-md p-3 pr-20 overflow-x-auto"
                data-testid="checklist-curl"
              >
                {curl}
              </pre>
              <button
                type="button"
                onClick={() => void copy()}
                className="absolute top-2 right-2 px-2 py-1 rounded bg-slate-700 text-slate-100 text-xs hover:bg-slate-600"
                data-testid="checklist-copy-curl"
              >
                {copied ? 'Copied' : 'Copy'}
              </button>
            </div>
          </div>
        </li>
      </ol>
    </div>
  );
}

export default FirstRunChecklist;
