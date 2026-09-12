import React, { useState, useEffect } from 'react';
import { useRouter } from 'next/router';
import Link from 'next/link';
import { TargetingRuleBuilder } from '@/components/targeting';
import { TargetingRules } from '@/types/targeting';
import { jsonToRules } from '@/utils/targeting';
import { FeatureFlag, FeatureFlagsService } from '@/services/featureFlags';
import { PageTitle } from '@/components/PageTitle';

const STATUS_COLORS: Record<string, string> = {
  active: 'bg-green-100 text-green-800',
  inactive: 'bg-slate-100 text-slate-700',
  archived: 'bg-gray-100 text-gray-600',
};

export default function FeatureFlagDetailPage() {
  const router = useRouter();
  const { id } = router.query;

  const [flag, setFlag] = useState<FeatureFlag | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saveSuccess, setSaveSuccess] = useState(false);

  // Editable fields
  const [rules, setRules] = useState<TargetingRules | null>(null);
  const [rolloutPercentage, setRolloutPercentage] = useState(0);

  useEffect(() => {
    if (!id || typeof id !== 'string') return;

    const fetchFlag = async () => {
      try {
        setIsLoading(true);
        setError(null);
        const data = await FeatureFlagsService.get(id);
        setFlag(data);
        setRules(data.targeting_rules ? jsonToRules(data.targeting_rules) : null);
        setRolloutPercentage(data.rollout_percentage);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to load feature flag');
      } finally {
        setIsLoading(false);
      }
    };

    fetchFlag();
  }, [id]);

  const handleSave = async () => {
    if (!flag) return;
    setSaveError(null);
    setSaveSuccess(false);
    setIsSaving(true);

    try {
      const updated = await FeatureFlagsService.update(flag.id, {
        targeting_rules: rules,
        rollout_percentage: rolloutPercentage,
      });
      setFlag(updated);
      setSaveSuccess(true);
      setTimeout(() => setSaveSuccess(false), 3000);
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : 'Failed to save changes');
    } finally {
      setIsSaving(false);
    }
  };

  if (isLoading) {
    return (
      <div className="flex-1 bg-slate-50 flex items-center justify-center">
        <PageTitle title="Feature Flag" />
        <div className="text-center">
          <div className="inline-block w-6 h-6 border-2 border-blue-600 border-t-transparent rounded-full animate-spin" />
          <p className="text-slate-500 mt-2 text-sm">Loading feature flag...</p>
        </div>
      </div>
    );
  }

  if (error || !flag) {
    return (
      <div className="flex-1 bg-slate-50 flex items-center justify-center">
        <PageTitle title="Feature Flag" />
        <div className="text-center">
          <p className="text-red-600 mb-4">{error ?? 'Feature flag not found'}</p>
          <Link
            href="/feature-flags"
            className="text-blue-600 hover:underline text-sm"
          >
            &larr; Back to Feature Flags
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 bg-slate-50">
      <PageTitle title={flag.name} />
      <div className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Header */}
        <div className="flex items-center gap-4 mb-6">
          <Link
            href="/feature-flags"
            className="text-slate-500 hover:text-slate-700 text-sm"
          >
            &larr; Feature Flags
          </Link>
        </div>

        <div className="flex items-start justify-between mb-6">
          <div>
            <div className="flex items-center gap-3">
              <h1 className="text-2xl font-bold text-slate-900" data-testid="flag-name">
                {flag.name}
              </h1>
              <span
                className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${STATUS_COLORS[flag.status] ?? 'bg-slate-100 text-slate-700'}`}
                data-testid="flag-status"
              >
                {flag.status}
              </span>
            </div>
            <p className="text-sm text-slate-500 mt-1 font-mono" data-testid="flag-key">
              {flag.key}
            </p>
            {flag.description && (
              <p className="text-sm text-slate-600 mt-2">{flag.description}</p>
            )}
          </div>
        </div>

        <div className="space-y-6">
          {/* Targeting Rules */}
          <section className="bg-white rounded-lg border border-slate-200 p-6">
            <TargetingRuleBuilder
              value={rules}
              onChange={setRules}
              data-testid="targeting-rule-builder"
            />
          </section>

          {/* Rollout Percentage */}
          <section className="bg-white rounded-lg border border-slate-200 p-6 space-y-4">
            <h2 className="text-base font-semibold text-slate-800">Rollout</h2>
            <div>
              <div className="flex items-center justify-between mb-2">
                <label className="text-sm font-medium text-slate-700">
                  Rollout percentage
                </label>
                <span className="text-sm font-semibold text-slate-900" data-testid="rollout-value">
                  {rolloutPercentage}%
                </span>
              </div>
              <input
                type="range"
                min={0}
                max={100}
                value={rolloutPercentage}
                onChange={(e) => setRolloutPercentage(Number(e.target.value))}
                className="w-full accent-blue-600"
                data-testid="rollout-percentage"
              />
              <div className="flex justify-between text-xs text-slate-400 mt-1">
                <span>0%</span>
                <span>100%</span>
              </div>
            </div>
          </section>

          {/* Save feedback */}
          {saveError && (
            <div className="rounded-lg bg-red-50 border border-red-200 p-3 text-sm text-red-700">
              {saveError}
            </div>
          )}
          {saveSuccess && (
            <div className="rounded-lg bg-green-50 border border-green-200 p-3 text-sm text-green-700">
              Changes saved successfully.
            </div>
          )}

          {/* Save button */}
          <div className="flex justify-end">
            <button
              type="button"
              onClick={handleSave}
              disabled={isSaving}
              className="px-6 py-2 rounded-lg bg-blue-600 text-white text-sm font-medium hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              data-testid="save-flag"
            >
              {isSaving ? 'Saving...' : 'Save Changes'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
