import React, { useState, useEffect, useCallback } from 'react';
import { ResultsService } from '@/services/results';
import {
  ExperimentResultsResponse,
  DailyResultsResponse,
  SampleSizeResult,
  DimensionalBreakdownResponse,
} from '@/types/results';
import { SequentialTestingResponse } from '@/types/sequential';
import { ExperimentSummary } from './ExperimentSummary';
import { SampleSizeMeter } from './SampleSizeMeter';
import { ConversionChart } from '@/components/results/Visualizations/ConversionChart';
import { TrendChart } from '@/components/results/Visualizations/TrendChart';
import { MetricComparisonTable } from '@/components/results/MetricComparison/MetricComparisonTable';
import { SequentialMonitor } from '@/components/results/Sequential/SequentialMonitor';
import { BreakdownSelector } from '@/components/results/Breakdowns/BreakdownSelector';
import { SegmentComparisonTable } from '@/components/results/Breakdowns/SegmentComparisonTable';

interface ResultsDashboardProps {
  experimentId: string;
}

type Tab = 'overview' | 'trends' | 'sample-size' | 'sequential' | 'breakdowns';

function LoadingSkeleton() {
  return (
    <div className="space-y-6 animate-pulse" data-testid="loading-skeleton">
      <div className="h-36 bg-slate-200 rounded-xl" />
      <div className="h-8 bg-slate-200 rounded w-64" />
      <div className="h-72 bg-slate-200 rounded-xl" />
      <div className="h-48 bg-slate-200 rounded-xl" />
    </div>
  );
}

export function ResultsDashboard({ experimentId }: ResultsDashboardProps) {
  const [results, setResults] = useState<ExperimentResultsResponse | null>(null);
  const [daily, setDaily] = useState<DailyResultsResponse | null>(null);
  const [sampleSize, setSampleSize] = useState<SampleSizeResult | null>(null);
  const [sequential, setSequential] = useState<SequentialTestingResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<Tab>('overview');
  // Issue #28: Breakdown state
  const [selectedBreakdown, setSelectedBreakdown] = useState<string | null>(null);
  const [breakdown, setBreakdown] = useState<DimensionalBreakdownResponse | null>(null);
  const [breakdownLoading, setBreakdownLoading] = useState(false);

  const fetchAll = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [r, d, s] = await Promise.all([
        ResultsService.getResults(experimentId),
        ResultsService.getDailyResults(experimentId),
        ResultsService.getSampleSize(experimentId),
      ]);
      setResults(r);
      setDaily(d);
      setSampleSize(s);

      // Fetch sequential data if available (inline or via dedicated endpoint)
      if (r.sequential_testing) {
        setSequential(r.sequential_testing);
      } else {
        // Try dedicated endpoint — swallow errors for non-sequential experiments
        try {
          const seq = await ResultsService.getSequentialResults(experimentId);
          setSequential(seq);
        } catch {
          setSequential(null);
        }
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load results');
    } finally {
      setLoading(false);
    }
  }, [experimentId]);

  // Issue #28: Fetch breakdown when dimension changes
  const fetchBreakdown = useCallback(async (dim: string | null) => {
    if (!dim) {
      setBreakdown(null);
      return;
    }
    setBreakdownLoading(true);
    try {
      const r = await ResultsService.getResults(experimentId, { breakdown: dim });
      setBreakdown(r.breakdown ?? null);
    } catch {
      setBreakdown(null);
    } finally {
      setBreakdownLoading(false);
    }
  }, [experimentId]);

  useEffect(() => {
    fetchAll();
  }, [fetchAll]);

  // Issue #28: fetch breakdown when selectedBreakdown changes
  useEffect(() => {
    fetchBreakdown(selectedBreakdown);
  }, [selectedBreakdown, fetchBreakdown]);

  if (loading) return <LoadingSkeleton />;

  if (error) {
    return (
      <div
        className="text-center py-16 space-y-4"
        data-testid="error-state"
        role="alert"
      >
        <p className="text-red-600 font-medium">Failed to load results: {error}</p>
        <button
          onClick={fetchAll}
          className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700"
        >
          Retry
        </button>
      </div>
    );
  }

  if (!results) return null;

  const primaryMetric = results.metrics.find((m) => m.is_primary) ?? results.metrics[0];

  const TABS: { id: Tab; label: string }[] = [
    { id: 'overview', label: 'Overview' },
    { id: 'trends', label: 'Trends' },
    { id: 'sample-size', label: 'Sample Size' },
    ...(sequential ? [{ id: 'sequential' as Tab, label: 'Sequential' }] : []),
    { id: 'breakdowns', label: 'Breakdowns' },
  ];

  return (
    <div className="space-y-6" data-testid="results-dashboard">
      <ExperimentSummary experiment={results} />

      {/* Tab navigation */}
      <nav
        className="flex gap-1 border-b border-slate-200"
        aria-label="Results sections"
        role="tablist"
      >
        {TABS.map((tab) => (
          <button
            key={tab.id}
            role="tab"
            aria-selected={activeTab === tab.id}
            aria-controls={`panel-${tab.id}`}
            onClick={() => setActiveTab(tab.id)}
            className={`px-4 py-2 text-sm font-medium rounded-t border-b-2 transition-colors ${
              activeTab === tab.id
                ? 'border-blue-600 text-blue-600'
                : 'border-transparent text-slate-600 hover:text-slate-900 hover:border-slate-300'
            }`}
          >
            {tab.label}
          </button>
        ))}
      </nav>

      {/* Tab panels */}
      <div id={`panel-${activeTab}`} role="tabpanel">
        {activeTab === 'overview' && (
          <div className="space-y-8">
            {/* No data guard */}
            {!results.metrics.length ? (
              <p className="text-slate-500 text-sm">No metrics available</p>
            ) : (
              <>
                {primaryMetric && (
                  <section aria-label="Conversion rates">
                    <h3 className="text-base font-semibold text-slate-800 mb-4">
                      Conversion Rates — {primaryMetric.metric_name}
                    </h3>
                    <ConversionChart variants={primaryMetric.variants} />
                  </section>
                )}
                <section aria-label="Metric comparison">
                  <h3 className="text-base font-semibold text-slate-800 mb-4">
                    All Metrics
                  </h3>
                  <MetricComparisonTable
                    metrics={results.metrics}
                    confidenceLevel={results.confidence_level}
                  />
                </section>
              </>
            )}
          </div>
        )}

        {activeTab === 'trends' && (
          <section aria-label="Trends over time">
            <h3 className="text-base font-semibold text-slate-800 mb-4">
              Daily Trends
            </h3>
            <TrendChart series={daily?.series ?? []} />
          </section>
        )}

        {activeTab === 'sample-size' && sampleSize && (
          <section
            className="max-w-lg"
            aria-label="Sample size adequacy"
          >
            <h3 className="text-base font-semibold text-slate-800 mb-4">
              Sample Size Analysis
            </h3>
            <SampleSizeMeter data={sampleSize} />
          </section>
        )}

        {activeTab === 'sequential' && sequential && (
          <section aria-label="Sequential testing">
            <h3 className="text-base font-semibold text-slate-800 mb-4">
              Sequential Testing Monitor
            </h3>
            <SequentialMonitor data={sequential} />
          </section>
        )}

        {/* Issue #28: Breakdowns tab */}
        {activeTab === 'breakdowns' && (
          <section aria-label="Segment breakdowns">
            <div className="space-y-6">
              <div>
                <h3 className="text-base font-semibold text-slate-800 mb-4">
                  Segment Breakdowns
                </h3>
                <BreakdownSelector
                  value={selectedBreakdown}
                  onChange={setSelectedBreakdown}
                />
              </div>

              {breakdownLoading && (
                <div className="animate-pulse space-y-2">
                  <div className="h-8 bg-slate-200 rounded w-full" />
                  <div className="h-48 bg-slate-200 rounded w-full" />
                </div>
              )}

              {!breakdownLoading && breakdown && (
                <SegmentComparisonTable breakdown={breakdown} />
              )}

              {!breakdownLoading && !breakdown && selectedBreakdown && (
                <p className="text-sm text-slate-500">
                  No breakdown data available for the selected dimension.
                </p>
              )}

              {!selectedBreakdown && (
                <p className="text-sm text-slate-500">
                  Select a dimension above to view segment-level results.
                </p>
              )}
            </div>
          </section>
        )}
      </div>
    </div>
  );
}
