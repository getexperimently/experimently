import React, { useMemo, useState } from 'react';
import { useRouter } from 'next/router';
import Link from 'next/link';
import { TargetingRuleBuilder } from '@/components/targeting';
import { TargetingRules } from '@/types/targeting';
import { createEmptyRules } from '@/utils/targeting';
import {
  ExperimentType,
  MetricType,
  EXPERIMENT_TYPE_LABELS,
  METRIC_TYPE_LABELS,
  CreateExperimentRequest,
} from '@/types/experiments';
import { ExperimentsService } from '@/services/experiments';
import { PageTitle } from '@/components/PageTitle';

export function generateKey(name: string): string {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')
    .substring(0, 64);
}

interface VariantFormData {
  name: string;
  description: string;
  traffic_allocation: number;
  is_control: boolean;
}

interface MetricFormData {
  name: string;
  event_name: string;
  metric_type: MetricType;
  is_primary: boolean;
}

const DEFAULT_VARIANTS: VariantFormData[] = [
  { name: 'Control', description: '', traffic_allocation: 50, is_control: true },
  { name: 'Treatment', description: '', traffic_allocation: 50, is_control: false },
];

const DEFAULT_METRICS: MetricFormData[] = [
  { name: 'Conversion', event_name: 'conversion', metric_type: 'conversion', is_primary: true },
];

/**
 * Types this form can fully configure.
 *
 * `split_url` needs a `split_url_config` (without it the split-URL path has no
 * URLs to route to) and `bandit` needs `optimization_type != "fixed"` (with the
 * default `fixed` the bandit scheduler skips the experiment forever, so traffic
 * never adapts). This form sends neither field, so it must not offer them —
 * see `backend/app/schemas/experiment.py::ExperimentCreate`.
 */
export const FORM_EXPERIMENT_TYPES: ExperimentType[] = ['a_b', 'mv'];

const EXPERIMENT_TYPES: Array<{ value: ExperimentType; label: string }> = FORM_EXPERIMENT_TYPES.map(
  (value) => ({ value, label: EXPERIMENT_TYPE_LABELS[value] }),
);

const METRIC_TYPES: Array<{ value: MetricType; label: string }> = (
  Object.keys(METRIC_TYPE_LABELS) as MetricType[]
).map((value) => ({ value, label: METRIC_TYPE_LABELS[value] }));

/** Client-side mirror of the `ExperimentCreate` validators; returns the first problem. */
export function validateForm(
  name: string,
  variants: VariantFormData[],
  metrics: MetricFormData[],
): string | null {
  if (!name.trim()) return 'Name is required.';
  if (variants.length === 0) return 'Add at least one variant.';
  if (variants.some((v) => !v.name.trim())) return 'Every variant needs a name.';
  if (!variants.some((v) => v.is_control)) return 'One variant must be marked as control.';
  const total = variants.reduce((sum, v) => sum + (Number(v.traffic_allocation) || 0), 0);
  if (total !== 100) return `Variant allocations must add up to 100% (currently ${total}%).`;
  if (metrics.length === 0) return 'Add at least one metric.';
  if (metrics.some((m) => !m.name.trim() || !m.event_name.trim())) {
    return 'Every metric needs a name and an event name.';
  }
  if (!metrics.some((m) => m.is_primary)) return 'Choose a primary metric.';
  return null;
}

const inputClass =
  'w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400';
const smallInputClass =
  'rounded border border-slate-300 px-2 py-1 text-sm focus:outline-none focus:ring-1 focus:ring-blue-400';

export default function NewExperimentPage() {
  const router = useRouter();
  const [name, setName] = useState('');
  const [key, setKey] = useState('');
  const [keyEdited, setKeyEdited] = useState(false);
  const [description, setDescription] = useState('');
  const [hypothesis, setHypothesis] = useState('');
  const [type, setType] = useState<ExperimentType>('a_b');
  const [rules, setRules] = useState<TargetingRules>(createEmptyRules());
  const [variants, setVariants] = useState<VariantFormData[]>(DEFAULT_VARIANTS);
  const [metrics, setMetrics] = useState<MetricFormData[]>(DEFAULT_METRICS);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const allocationTotal = useMemo(
    () => variants.reduce((sum, v) => sum + (Number(v.traffic_allocation) || 0), 0),
    [variants],
  );

  const handleNameChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const newName = e.target.value;
    setName(newName);
    if (!keyEdited) setKey(generateKey(newName));
  };

  const handleKeyChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setKey(e.target.value);
    setKeyEdited(true);
  };

  // --- variants -----------------------------------------------------------
  const handleAddVariant = () => {
    setVariants([
      ...variants,
      { name: `Variant ${variants.length}`, description: '', traffic_allocation: 0, is_control: false },
    ]);
  };

  const handleRemoveVariant = (index: number) => {
    setVariants(variants.filter((_, i) => i !== index));
  };

  const handleVariantChange = (
    index: number,
    field: keyof VariantFormData,
    value: string | number | boolean,
  ) => {
    setVariants(variants.map((v, i) => (i === index ? { ...v, [field]: value } : v)));
  };

  const handleSetControl = (index: number) => {
    setVariants(variants.map((v, i) => ({ ...v, is_control: i === index })));
  };

  // --- metrics ------------------------------------------------------------
  const handleAddMetric = () => {
    setMetrics([
      ...metrics,
      { name: '', event_name: '', metric_type: 'conversion', is_primary: metrics.length === 0 },
    ]);
  };

  const handleRemoveMetric = (index: number) => {
    const next = metrics.filter((_, i) => i !== index);
    if (next.length > 0 && !next.some((m) => m.is_primary)) next[0] = { ...next[0], is_primary: true };
    setMetrics(next);
  };

  const handleMetricChange = (
    index: number,
    field: keyof MetricFormData,
    value: string | boolean,
  ) => {
    setMetrics(metrics.map((m, i) => (i === index ? { ...m, [field]: value } : m)));
  };

  const handleSetPrimary = (index: number) => {
    setMetrics(metrics.map((m, i) => ({ ...m, is_primary: i === index })));
  };

  // --- submit -------------------------------------------------------------
  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    const problem = validateForm(name, variants, metrics);
    if (problem) {
      setError(problem);
      return;
    }

    setIsSubmitting(true);
    try {
      const payload: CreateExperimentRequest = {
        name: name.trim(),
        key: (key || generateKey(name)).trim() || undefined,
        description: description.trim() || undefined,
        hypothesis: hypothesis.trim() || undefined,
        experiment_type: type,
        targeting_rules: rules.groups.length > 0 ? (rules as unknown as Record<string, unknown>) : null,
        variants: variants.map((v) => ({
          name: v.name.trim(),
          description: v.description.trim() || undefined,
          is_control: v.is_control,
          traffic_allocation: Number(v.traffic_allocation) || 0,
        })),
        metrics: metrics.map((m) => ({
          name: m.name.trim(),
          event_name: m.event_name.trim(),
          metric_type: m.metric_type,
          is_primary: m.is_primary,
        })),
      };

      const created = await ExperimentsService.create(payload);
      await router.push(`/experiments/${created.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create experiment');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="flex-1 bg-slate-50">
      <PageTitle title="New Experiment" />
      <div className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Header */}
        <div className="flex items-center gap-4 mb-6">
          <Link href="/experiments" className="text-slate-500 hover:text-slate-700 text-sm">
            &larr; Experiments
          </Link>
          <h1 className="text-2xl font-bold text-slate-900">New Experiment</h1>
        </div>

        <form onSubmit={handleSubmit} className="space-y-6" data-testid="new-experiment-form" noValidate>
          {/* Basic info */}
          <section className="bg-white rounded-lg border border-slate-200 p-6 space-y-4">
            <h2 className="text-base font-semibold text-slate-800">Basic Information</h2>

            <div>
              <label htmlFor="experiment-name" className="block text-sm font-medium text-slate-700 mb-1">
                Name <span className="text-red-500">*</span>
              </label>
              <input
                id="experiment-name"
                name="name"
                type="text"
                required
                value={name}
                onChange={handleNameChange}
                placeholder="My Experiment"
                className={inputClass}
                data-testid="experiment-name"
              />
            </div>

            <div>
              <label htmlFor="experiment-key" className="block text-sm font-medium text-slate-700 mb-1">
                Key
              </label>
              <input
                id="experiment-key"
                name="key"
                type="text"
                value={key}
                onChange={handleKeyChange}
                placeholder="my_experiment"
                className={`${inputClass} font-mono`}
                data-testid="experiment-key"
              />
              <p className="text-xs text-slate-400 mt-1">
                Auto-generated from the name. SDKs use it in <code className="font-mono">experiment_key</code>.
              </p>
            </div>

            <div>
              <label htmlFor="experiment-description" className="block text-sm font-medium text-slate-700 mb-1">
                Description
              </label>
              <textarea
                id="experiment-description"
                name="description"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                rows={2}
                placeholder="What is this experiment testing?"
                className={`${inputClass} resize-none`}
                data-testid="experiment-description"
              />
            </div>

            <div>
              <label htmlFor="experiment-hypothesis" className="block text-sm font-medium text-slate-700 mb-1">
                Hypothesis
              </label>
              <textarea
                id="experiment-hypothesis"
                name="hypothesis"
                value={hypothesis}
                onChange={(e) => setHypothesis(e.target.value)}
                rows={2}
                placeholder="We believe that... will result in..."
                className={`${inputClass} resize-none`}
                data-testid="experiment-hypothesis"
              />
            </div>

            <div>
              <label htmlFor="experiment-type" className="block text-sm font-medium text-slate-700 mb-1">
                Experiment Type
              </label>
              <select
                id="experiment-type"
                name="experiment_type"
                value={type}
                onChange={(e) => setType(e.target.value as ExperimentType)}
                className={inputClass}
                data-testid="experiment-type"
              >
                {EXPERIMENT_TYPES.map((t) => (
                  <option key={t.value} value={t.value}>
                    {t.label}
                  </option>
                ))}
              </select>
              <p className="text-xs text-slate-400 mt-1" data-testid="experiment-type-note">
                <Link
                  href="/docs/experiments/split-url"
                  className="text-blue-600 hover:text-blue-800 hover:underline"
                >
                  Split URL
                </Link>{' '}
                experiments need a URL configuration and{' '}
                <Link
                  href="/docs/experiments/mab"
                  className="text-blue-600 hover:text-blue-800 hover:underline"
                >
                  bandit
                </Link>{' '}
                experiments need an optimization algorithm — neither can be set up from this form
                yet, so create them through the API or an SDK.
              </p>
            </div>
          </section>

          {/* Variants */}
          <section className="bg-white rounded-lg border border-slate-200 p-6 space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-base font-semibold text-slate-800">Variants</h2>
                <p className="text-xs text-slate-500 mt-0.5">
                  Allocations must add up to 100%.{' '}
                  <span
                    className={allocationTotal === 100 ? 'text-green-700' : 'text-red-600'}
                    data-testid="allocation-total"
                  >
                    Currently {allocationTotal}%
                  </span>
                </p>
              </div>
              <button
                type="button"
                onClick={handleAddVariant}
                className="text-sm text-blue-600 hover:text-blue-800 font-medium"
                data-testid="add-variant"
              >
                + Add Variant
              </button>
            </div>

            <div className="space-y-3">
              {variants.map((variant, index) => (
                <div
                  key={index}
                  className="flex gap-3 items-start p-3 rounded-lg border border-slate-200 bg-slate-50"
                  data-testid={`variant-row-${index}`}
                >
                  <div className="flex-1 space-y-2">
                    <div className="flex gap-2">
                      <input
                        type="text"
                        name={`variant_name_${index}`}
                        value={variant.name}
                        onChange={(e) => handleVariantChange(index, 'name', e.target.value)}
                        placeholder="Variant name"
                        aria-label={`Variant ${index + 1} name`}
                        className={`flex-1 ${smallInputClass}`}
                        data-testid={`variant-name-${index}`}
                      />
                      <div className="flex items-center gap-1">
                        <input
                          type="number"
                          name={`variant_allocation_${index}`}
                          min={0}
                          max={100}
                          value={variant.traffic_allocation}
                          onChange={(e) =>
                            handleVariantChange(index, 'traffic_allocation', Number(e.target.value))
                          }
                          aria-label={`Variant ${index + 1} allocation`}
                          className={`w-16 text-center ${smallInputClass}`}
                          data-testid={`variant-allocation-${index}`}
                        />
                        <span className="text-xs text-slate-500">%</span>
                      </div>
                    </div>
                    <label className="inline-flex items-center gap-1.5 text-xs text-slate-600">
                      <input
                        type="radio"
                        name="control_variant"
                        checked={variant.is_control}
                        onChange={() => handleSetControl(index)}
                        data-testid={`variant-control-${index}`}
                      />
                      Control
                    </label>
                  </div>
                  {variants.length > 1 && (
                    <button
                      type="button"
                      onClick={() => handleRemoveVariant(index)}
                      className="text-red-400 hover:text-red-600 text-sm mt-1"
                      data-testid={`remove-variant-${index}`}
                      aria-label="Remove variant"
                    >
                      &times;
                    </button>
                  )}
                </div>
              ))}
            </div>
          </section>

          {/* Metrics */}
          <section className="bg-white rounded-lg border border-slate-200 p-6 space-y-4" data-testid="metrics-section">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-base font-semibold text-slate-800">Metrics</h2>
                <p className="text-xs text-slate-500 mt-0.5">
                  Conversions are matched by <span className="font-mono">event_name</span> from{' '}
                  <span className="font-mono">/tracking/track</span>. One metric is primary.
                </p>
              </div>
              <button
                type="button"
                onClick={handleAddMetric}
                className="text-sm text-blue-600 hover:text-blue-800 font-medium"
                data-testid="add-metric"
              >
                + Add Metric
              </button>
            </div>

            <div className="space-y-3">
              {metrics.map((metric, index) => (
                <div
                  key={index}
                  className="flex gap-3 items-start p-3 rounded-lg border border-slate-200 bg-slate-50"
                  data-testid={`metric-row-${index}`}
                >
                  <div className="flex-1 space-y-2">
                    <div className="flex flex-col sm:flex-row gap-2">
                      <input
                        type="text"
                        name={`metric_name_${index}`}
                        value={metric.name}
                        onChange={(e) => handleMetricChange(index, 'name', e.target.value)}
                        placeholder="Metric name"
                        aria-label={`Metric ${index + 1} name`}
                        className={`flex-1 ${smallInputClass}`}
                        data-testid={`metric-name-${index}`}
                      />
                      <input
                        type="text"
                        name={`metric_event_${index}`}
                        value={metric.event_name}
                        onChange={(e) => handleMetricChange(index, 'event_name', e.target.value)}
                        placeholder="event_name (e.g. purchase)"
                        aria-label={`Metric ${index + 1} event name`}
                        className={`flex-1 font-mono ${smallInputClass}`}
                        data-testid={`metric-event-${index}`}
                      />
                      <select
                        name={`metric_type_${index}`}
                        value={metric.metric_type}
                        onChange={(e) => handleMetricChange(index, 'metric_type', e.target.value)}
                        aria-label={`Metric ${index + 1} type`}
                        className={smallInputClass}
                        data-testid={`metric-type-${index}`}
                      >
                        {METRIC_TYPES.map((t) => (
                          <option key={t.value} value={t.value}>
                            {t.label}
                          </option>
                        ))}
                      </select>
                    </div>
                    <label className="inline-flex items-center gap-1.5 text-xs text-slate-600">
                      <input
                        type="radio"
                        name="primary_metric"
                        checked={metric.is_primary}
                        onChange={() => handleSetPrimary(index)}
                        data-testid={`metric-primary-${index}`}
                      />
                      Primary metric
                    </label>
                  </div>
                  {metrics.length > 1 && (
                    <button
                      type="button"
                      onClick={() => handleRemoveMetric(index)}
                      className="text-red-400 hover:text-red-600 text-sm mt-1"
                      data-testid={`remove-metric-${index}`}
                      aria-label="Remove metric"
                    >
                      &times;
                    </button>
                  )}
                </div>
              ))}
            </div>
          </section>

          {/* Targeting Rules */}
          <section className="bg-white rounded-lg border border-slate-200 p-6">
            <TargetingRuleBuilder value={rules} onChange={setRules} />
          </section>

          {/* Error message */}
          {error && (
            <div
              role="alert"
              className="rounded-lg bg-red-50 border border-red-200 p-3 text-sm text-red-700"
              data-testid="form-error"
            >
              {error}
            </div>
          )}

          {/* Submit */}
          <div className="flex gap-3 justify-end">
            <Link
              href="/experiments"
              className="px-4 py-2 rounded-lg border border-slate-300 text-sm font-medium text-slate-600 hover:bg-slate-50 transition-colors"
            >
              Cancel
            </Link>
            <button
              type="submit"
              disabled={isSubmitting}
              className="px-6 py-2 rounded-lg bg-blue-600 text-white text-sm font-medium hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              data-testid="submit-experiment"
            >
              {isSubmitting ? 'Creating...' : 'Create Experiment'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
