import React, { useState } from 'react';
import { useRouter } from 'next/router';
import Link from 'next/link';
import { TargetingRuleBuilder } from '@/components/targeting';
import { TargetingRules } from '@/types/targeting';
import { createEmptyRules } from '@/utils/targeting';
import {
  ExperimentType,
  ExperimentVariant,
  EXPERIMENT_TYPE_LABELS,
  CreateExperimentRequest,
} from '@/types/experiments';
import { ExperimentsService } from '@/services/experiments';
import { PageTitle } from '@/components/PageTitle';

function generateKey(name: string): string {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')
    .substring(0, 64);
}

interface VariantFormData {
  name: string;
  description: string;
  allocation: number;
  is_control: boolean;
}

const DEFAULT_VARIANTS: VariantFormData[] = [
  { name: 'Control', description: '', allocation: 50, is_control: true },
  { name: 'Treatment', description: '', allocation: 50, is_control: false },
];

const EXPERIMENT_TYPES: Array<{ value: ExperimentType; label: string }> = [
  { value: 'a_b', label: EXPERIMENT_TYPE_LABELS['a_b'] },
  { value: 'mv', label: EXPERIMENT_TYPE_LABELS['mv'] },
  { value: 'split_url', label: EXPERIMENT_TYPE_LABELS['split_url'] },
  { value: 'bandit', label: EXPERIMENT_TYPE_LABELS['bandit'] },
];

export default function NewExperimentPage() {
  const router = useRouter();
  const [name, setName] = useState('');
  const [key, setKey] = useState('');
  const [keyEdited, setKeyEdited] = useState(false);
  const [description, setDescription] = useState('');
  const [hypothesis, setHypothesis] = useState('');
  const [type, setType] = useState<ExperimentType>('a_b');
  const [trafficAllocation, setTrafficAllocation] = useState(100);
  const [rules, setRules] = useState<TargetingRules>(createEmptyRules());
  const [variants, setVariants] = useState<VariantFormData[]>(DEFAULT_VARIANTS);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleNameChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const newName = e.target.value;
    setName(newName);
    if (!keyEdited) {
      setKey(generateKey(newName));
    }
  };

  const handleKeyChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setKey(e.target.value);
    setKeyEdited(true);
  };

  const handleAddVariant = () => {
    setVariants([
      ...variants,
      { name: `Variant ${variants.length}`, description: '', allocation: 0, is_control: false },
    ]);
  };

  const handleRemoveVariant = (index: number) => {
    setVariants(variants.filter((_, i) => i !== index));
  };

  const handleVariantChange = (
    index: number,
    field: keyof VariantFormData,
    value: string | number | boolean
  ) => {
    setVariants(variants.map((v, i) => (i === index ? { ...v, [field]: value } : v)));
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setIsSubmitting(true);

    try {
      const payload: CreateExperimentRequest = {
        name,
        key: key || generateKey(name),
        description: description || undefined,
        hypothesis: hypothesis || undefined,
        type,
        traffic_allocation: trafficAllocation,
        targeting_rules: rules.groups.length > 0 ? rules : null,
        variants: variants.map((v) => ({
          name: v.name,
          description: v.description || undefined,
          allocation: v.allocation,
          is_control: v.is_control,
        })),
      };

      const created = await ExperimentsService.create(payload);
      router.push(`/experiments/${created.id}`);
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

        <form onSubmit={handleSubmit} className="space-y-6">
          {/* Basic info */}
          <section className="bg-white rounded-lg border border-slate-200 p-6 space-y-4">
            <h2 className="text-base font-semibold text-slate-800">Basic Information</h2>

            <div>
              <label className="block text-sm font-medium text-slate-700 mb-1">
                Name <span className="text-red-500">*</span>
              </label>
              <input
                type="text"
                required
                value={name}
                onChange={handleNameChange}
                placeholder="My Experiment"
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400"
                data-testid="experiment-name"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-slate-700 mb-1">
                Key <span className="text-red-500">*</span>
              </label>
              <input
                type="text"
                required
                value={key}
                onChange={handleKeyChange}
                placeholder="my_experiment"
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-blue-400"
                data-testid="experiment-key"
              />
              <p className="text-xs text-slate-400 mt-1">
                Auto-generated from name. Used in SDK calls.
              </p>
            </div>

            <div>
              <label className="block text-sm font-medium text-slate-700 mb-1">
                Description
              </label>
              <textarea
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                rows={2}
                placeholder="What is this experiment testing?"
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400 resize-none"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-slate-700 mb-1">
                Hypothesis
              </label>
              <textarea
                value={hypothesis}
                onChange={(e) => setHypothesis(e.target.value)}
                rows={2}
                placeholder="We believe that... will result in..."
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400 resize-none"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-slate-700 mb-1">
                Experiment Type
              </label>
              <select
                value={type}
                onChange={(e) => setType(e.target.value as ExperimentType)}
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400"
                data-testid="experiment-type"
              >
                {EXPERIMENT_TYPES.map((t) => (
                  <option key={t.value} value={t.value}>
                    {t.label}
                  </option>
                ))}
              </select>
            </div>
          </section>

          {/* Targeting Rules */}
          <section className="bg-white rounded-lg border border-slate-200 p-6">
            <TargetingRuleBuilder value={rules} onChange={setRules} />
          </section>

          {/* Traffic allocation */}
          <section className="bg-white rounded-lg border border-slate-200 p-6 space-y-4">
            <h2 className="text-base font-semibold text-slate-800">Traffic Allocation</h2>
            <div>
              <div className="flex items-center justify-between mb-2">
                <label className="text-sm font-medium text-slate-700">
                  Traffic allocation
                </label>
                <span className="text-sm font-semibold text-slate-900">
                  {trafficAllocation}%
                </span>
              </div>
              <input
                type="range"
                min={0}
                max={100}
                value={trafficAllocation}
                onChange={(e) => setTrafficAllocation(Number(e.target.value))}
                className="w-full accent-blue-600"
                data-testid="traffic-allocation"
              />
              <div className="flex justify-between text-xs text-slate-400 mt-1">
                <span>0%</span>
                <span>100%</span>
              </div>
            </div>
          </section>

          {/* Variants */}
          <section className="bg-white rounded-lg border border-slate-200 p-6 space-y-4">
            <div className="flex items-center justify-between">
              <h2 className="text-base font-semibold text-slate-800">Variants</h2>
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
                        value={variant.name}
                        onChange={(e) => handleVariantChange(index, 'name', e.target.value)}
                        placeholder="Variant name"
                        className="flex-1 rounded border border-slate-300 px-2 py-1 text-sm focus:outline-none focus:ring-1 focus:ring-blue-400"
                        data-testid={`variant-name-${index}`}
                      />
                      <div className="flex items-center gap-1">
                        <input
                          type="number"
                          min={0}
                          max={100}
                          value={variant.allocation}
                          onChange={(e) =>
                            handleVariantChange(index, 'allocation', Number(e.target.value))
                          }
                          className="w-16 rounded border border-slate-300 px-2 py-1 text-sm text-center focus:outline-none focus:ring-1 focus:ring-blue-400"
                          data-testid={`variant-allocation-${index}`}
                        />
                        <span className="text-xs text-slate-500">%</span>
                      </div>
                    </div>
                    {variant.is_control && (
                      <span className="text-xs text-green-700 bg-green-100 px-2 py-0.5 rounded-full">
                        Control
                      </span>
                    )}
                  </div>
                  {!variant.is_control && (
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

          {/* Error message */}
          {error && (
            <div className="rounded-lg bg-red-50 border border-red-200 p-3 text-sm text-red-700">
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
