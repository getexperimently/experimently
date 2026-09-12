'use client';

import Link from 'next/link';
import { useState, useEffect, useCallback, useRef } from 'react';
import { apiFetch } from '@/services/api';
import { PageTitle } from '@/components/PageTitle';
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceDot,
} from 'recharts';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface SampleSizeResult {
  per_variant: number;
  total: number;
  alpha: number;
  power: number;
  baseline_rate: number;
  mde_absolute: number;
  mde_relative: number;
  confidence_level: number;
  runtime_days: number | null;
  n_variants: number;
  two_tailed: boolean;
  metric_type: string;
}

interface PowerCurvePoint {
  effect_size_relative: number;
  sample_size_per_variant: number;
  is_current_target: boolean;
}

interface PowerCurveResponse {
  points: PowerCurvePoint[];
  baseline_rate: number;
  alpha: number;
  power_target: number;
}

interface PlanAdvice {
  advice: string;
  generated_by: string;
  experiment_name: string;
  baseline_rate: number;
  mde: number;
  runtime_days: number;
}

// ---------------------------------------------------------------------------
// Utilities
// ---------------------------------------------------------------------------

function debounce<T extends (...args: Parameters<T>) => void>(
  fn: T,
  delay: number,
): (...args: Parameters<T>) => void {
  let timer: ReturnType<typeof setTimeout> | null = null;
  return (...args: Parameters<T>) => {
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => fn(...args), delay);
  };
}

function fmtNumber(n: number): string {
  return n.toLocaleString();
}

function fmtDays(d: number | null): string {
  if (d === null) return '--';
  if (d < 1) return '< 1 day';
  if (d < 7) return `${d.toFixed(1)} days`;
  const weeks = d / 7;
  return `${weeks.toFixed(1)} weeks (${Math.round(d)} days)`;
}

// ---------------------------------------------------------------------------
// API helpers
// ---------------------------------------------------------------------------

async function fetchSampleSize(params: {
  baseline_rate: number;
  minimum_detectable_effect: number;
  alpha: number;
  power: number;
  n_variants: number;
  daily_traffic: number | null;
  traffic_allocation: number;
}): Promise<SampleSizeResult> {
  const body: Record<string, unknown> = {
    baseline_rate: params.baseline_rate,
    minimum_detectable_effect: params.minimum_detectable_effect,
    alpha: params.alpha,
    power: params.power,
    n_variants: params.n_variants,
    two_tailed: true,
    metric_type: 'proportion',
    traffic_allocation: params.traffic_allocation,
  };
  if (params.daily_traffic !== null && params.daily_traffic > 0) {
    body.daily_traffic = params.daily_traffic;
  }
  return apiFetch<SampleSizeResult>('/api/v1/power/sample-size', { method: 'POST', json: body });
}

async function fetchPowerCurve(params: {
  baseline: number;
  alpha: number;
  power: number;
  mde: number;
}): Promise<PowerCurveResponse> {
  return apiFetch<PowerCurveResponse>('/api/v1/power/curve', {
    query: {
      baseline: params.baseline,
      alpha: params.alpha,
      power: params.power,
      mde: params.mde,
    },
  });
}

async function fetchPlanningAdvice(params: {
  experiment_name: string;
  metric_description: string;
  baseline_rate: number;
  mde: number;
  runtime_days: number;
  business_context: string;
}): Promise<PlanAdvice> {
  return apiFetch<PlanAdvice>('/api/v1/power/plan', { method: 'POST', json: params });
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function PowerCalculatorPage() {
  // Form state
  const [baselineRate, setBaselineRate] = useState<number>(0.05);
  const [mde, setMde] = useState<number>(0.10);
  const [alpha, setAlpha] = useState<number>(0.05);
  const [power, setPower] = useState<number>(0.80);
  const [nVariants, setNVariants] = useState<number>(2);
  const [dailyTraffic, setDailyTraffic] = useState<string>('');
  const [trafficAllocation, setTrafficAllocation] = useState<number>(1.0);

  // AI advice state
  const [experimentName, setExperimentName] = useState<string>('');
  const [metricDescription, setMetricDescription] = useState<string>('');
  const [businessContext, setBusinessContext] = useState<string>('');

  // Results state
  const [result, setResult] = useState<SampleSizeResult | null>(null);
  const [curveData, setCurveData] = useState<PowerCurvePoint[]>([]);
  const [advice, setAdvice] = useState<PlanAdvice | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [curveLoading, setCurveLoading] = useState<boolean>(false);
  const [adviceLoading, setAdviceLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [adviceError, setAdviceError] = useState<string | null>(null);

  // ---------------------------------------------------------------------------
  // Debounced calculation
  // ---------------------------------------------------------------------------

  const calculate = useCallback(async (
    baseline: number,
    mdeVal: number,
    alphaVal: number,
    powerVal: number,
    variants: number,
    traffic: string,
    allocation: number,
  ) => {
    // Validate
    if (baseline <= 0 || baseline >= 1) return;
    if (mdeVal <= 0 || mdeVal >= 1) return;
    if (alphaVal <= 0 || alphaVal >= 0.5) return;
    if (powerVal <= 0 || powerVal >= 1) return;
    if (baseline + baseline * mdeVal >= 1) return;

    setLoading(true);
    setError(null);

    const dailyTrafficNum = traffic.trim() ? parseInt(traffic, 10) : null;

    try {
      const [sampleResult, curveResult] = await Promise.all([
        fetchSampleSize({
          baseline_rate: baseline,
          minimum_detectable_effect: mdeVal,
          alpha: alphaVal,
          power: powerVal,
          n_variants: variants,
          daily_traffic: dailyTrafficNum,
          traffic_allocation: allocation,
        }),
        fetchPowerCurve({
          baseline,
          alpha: alphaVal,
          power: powerVal,
          mde: mdeVal,
        }),
      ]);
      setResult(sampleResult);
      setCurveData(curveResult.points);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Calculation failed';
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, []);

  // eslint-disable-next-line react-hooks/exhaustive-deps
  const debouncedCalculate = useCallback(
    debounce(calculate, 400),
    [calculate],
  );

  useEffect(() => {
    debouncedCalculate(
      baselineRate, mde, alpha, power, nVariants, dailyTraffic, trafficAllocation,
    );
  }, [baselineRate, mde, alpha, power, nVariants, dailyTraffic, trafficAllocation, debouncedCalculate]);

  // ---------------------------------------------------------------------------
  // AI advice
  // ---------------------------------------------------------------------------

  const getAdvice = async () => {
    if (!result) return;
    const name = experimentName.trim() || 'My Experiment';
    const metric = metricDescription.trim() || 'primary conversion metric';
    const runtime = result.runtime_days ?? 30;

    if (name.length < 3) {
      setAdviceError('Experiment name must be at least 3 characters.');
      return;
    }

    setAdviceLoading(true);
    setAdviceError(null);
    setAdvice(null);

    try {
      const plan = await fetchPlanningAdvice({
        experiment_name: name,
        metric_description: metric,
        baseline_rate: baselineRate,
        mde,
        runtime_days: runtime,
        business_context: businessContext,
      });
      setAdvice(plan);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to get advice';
      setAdviceError(msg);
    } finally {
      setAdviceLoading(false);
    }
  };

  // ---------------------------------------------------------------------------
  // Chart data transformation
  // ---------------------------------------------------------------------------

  const chartData = curveData.map((p) => ({
    effectPct: Math.round(p.effect_size_relative * 100),
    sampleSize: p.sample_size_per_variant,
    isTarget: p.is_current_target,
  }));

  const targetPoint = chartData.find((p) => p.isTarget);

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <>
      <PageTitle
        title="Power Calculator"
        description="Pre-experiment statistical power calculator: compute sample size, MDE, and runtime estimates for A/B tests. No login required."
      />

      <div className="flex-1 bg-gray-50">

        <div className="max-w-7xl mx-auto px-6 lg:px-8 py-10">
          {/* Header */}
          <div className="mb-8">
            <h1 className="text-3xl font-bold text-gray-900 mb-2">
              Pre-Experiment Power Calculator
            </h1>
            <p className="text-gray-500 text-base">
              Calculate the required sample size, detect the minimum effect size, and estimate
              how long your experiment needs to run. No account required.{' '}
              <Link href="/docs/statistics/power-analysis" className="text-blue-600 hover:text-blue-700">
                Learn more
              </Link>
            </p>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            {/* ----------------------------------------------------------------
                LEFT COLUMN: Inputs
            ---------------------------------------------------------------- */}
            <div className="lg:col-span-1 space-y-4">

              {/* Baseline Conversion Rate */}
              <div className="bg-white rounded-xl border border-gray-200 p-5">
                <h2 className="text-sm font-semibold text-gray-700 mb-4 uppercase tracking-wide">
                  Experiment Parameters
                </h2>

                <div className="space-y-5">
                  {/* Baseline Rate */}
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">
                      Baseline Conversion Rate
                      <span className="ml-2 text-blue-600 font-semibold">
                        {(baselineRate * 100).toFixed(1)}%
                      </span>
                    </label>
                    <input
                      type="range"
                      min="0.01"
                      max="0.50"
                      step="0.01"
                      value={baselineRate}
                      onChange={(e) => setBaselineRate(parseFloat(e.target.value))}
                      className="w-full accent-blue-600"
                    />
                    <div className="flex justify-between text-xs text-gray-400 mt-1">
                      <span>1%</span><span>50%</span>
                    </div>
                  </div>

                  {/* MDE */}
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">
                      Minimum Detectable Effect (relative)
                      <span className="ml-2 text-blue-600 font-semibold">
                        {(mde * 100).toFixed(0)}%
                      </span>
                    </label>
                    <input
                      type="range"
                      min="0.01"
                      max="0.50"
                      step="0.01"
                      value={mde}
                      onChange={(e) => setMde(parseFloat(e.target.value))}
                      className="w-full accent-blue-600"
                    />
                    <div className="flex justify-between text-xs text-gray-400 mt-1">
                      <span>1%</span><span>50%</span>
                    </div>
                  </div>

                  {/* Alpha */}
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">
                      Significance Level (alpha)
                    </label>
                    <select
                      value={alpha}
                      onChange={(e) => setAlpha(parseFloat(e.target.value))}
                      className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm text-gray-700 focus:ring-2 focus:ring-blue-500 focus:border-transparent outline-none"
                    >
                      <option value={0.01}>0.01 (99% confidence)</option>
                      <option value={0.05}>0.05 (95% confidence)</option>
                      <option value={0.10}>0.10 (90% confidence)</option>
                    </select>
                  </div>

                  {/* Power */}
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">
                      Statistical Power
                    </label>
                    <select
                      value={power}
                      onChange={(e) => setPower(parseFloat(e.target.value))}
                      className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm text-gray-700 focus:ring-2 focus:ring-blue-500 focus:border-transparent outline-none"
                    >
                      <option value={0.70}>0.70 (70%)</option>
                      <option value={0.80}>0.80 (80%) — recommended</option>
                      <option value={0.90}>0.90 (90%)</option>
                      <option value={0.95}>0.95 (95%)</option>
                    </select>
                  </div>

                  {/* Variants */}
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">
                      Number of Variants (including control)
                    </label>
                    <select
                      value={nVariants}
                      onChange={(e) => setNVariants(parseInt(e.target.value, 10))}
                      className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm text-gray-700 focus:ring-2 focus:ring-blue-500 focus:border-transparent outline-none"
                    >
                      <option value={2}>2 (A/B test)</option>
                      <option value={3}>3 (A/B/C test)</option>
                      <option value={4}>4 (A/B/C/D test)</option>
                      <option value={5}>5 variants</option>
                    </select>
                    {nVariants > 2 && (
                      <p className="text-xs text-amber-600 mt-1">
                        Bonferroni correction applied for {nVariants - 1} comparisons.
                      </p>
                    )}
                  </div>
                </div>
              </div>

              {/* Traffic */}
              <div className="bg-white rounded-xl border border-gray-200 p-5">
                <h2 className="text-sm font-semibold text-gray-700 mb-4 uppercase tracking-wide">
                  Traffic (optional — for runtime estimate)
                </h2>

                <div className="space-y-4">
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">
                      Daily Users
                    </label>
                    <input
                      type="number"
                      placeholder="e.g. 10000"
                      value={dailyTraffic}
                      onChange={(e) => setDailyTraffic(e.target.value)}
                      min="1"
                      className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm text-gray-700 focus:ring-2 focus:ring-blue-500 focus:border-transparent outline-none"
                    />
                  </div>

                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">
                      Traffic Allocation
                      <span className="ml-2 text-blue-600 font-semibold">
                        {(trafficAllocation * 100).toFixed(0)}%
                      </span>
                    </label>
                    <input
                      type="range"
                      min="0.05"
                      max="1.00"
                      step="0.05"
                      value={trafficAllocation}
                      onChange={(e) => setTrafficAllocation(parseFloat(e.target.value))}
                      className="w-full accent-blue-600"
                    />
                    <div className="flex justify-between text-xs text-gray-400 mt-1">
                      <span>5%</span><span>100%</span>
                    </div>
                  </div>
                </div>
              </div>

            </div>

            {/* ----------------------------------------------------------------
                MIDDLE + RIGHT: Results
            ---------------------------------------------------------------- */}
            <div className="lg:col-span-2 space-y-4">

              {/* Error Banner */}
              {error && (
                <div className="bg-red-50 border border-red-200 rounded-xl p-4 text-sm text-red-700">
                  {error}
                </div>
              )}

              {/* Key Metrics */}
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                <div className="bg-blue-600 text-white rounded-xl p-5">
                  <p className="text-xs font-medium opacity-80 uppercase tracking-wide mb-1">
                    Sample Size per Variant
                  </p>
                  <p className="text-3xl font-bold">
                    {loading ? '...' : result ? fmtNumber(result.per_variant) : '--'}
                  </p>
                  <p className="text-xs opacity-70 mt-1">
                    Total: {loading ? '...' : result ? fmtNumber(result.total) : '--'}
                  </p>
                </div>

                <div className="bg-white border border-gray-200 rounded-xl p-5">
                  <p className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-1">
                    MDE (absolute)
                  </p>
                  <p className="text-3xl font-bold text-gray-900">
                    {loading ? '...' : result ? `+${(result.mde_absolute * 100).toFixed(2)}%` : '--'}
                  </p>
                  <p className="text-xs text-gray-400 mt-1">
                    {result
                      ? `${(result.baseline_rate * 100).toFixed(2)}% → ${((result.baseline_rate + result.mde_absolute) * 100).toFixed(2)}%`
                      : 'baseline → treatment'}
                  </p>
                </div>

                <div className="bg-white border border-gray-200 rounded-xl p-5">
                  <p className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-1">
                    Estimated Runtime
                  </p>
                  <p className="text-3xl font-bold text-gray-900">
                    {loading ? '...' : fmtDays(result?.runtime_days ?? null)}
                  </p>
                  <p className="text-xs text-gray-400 mt-1">
                    {dailyTraffic ? '' : 'Enter daily traffic above'}
                  </p>
                </div>
              </div>

              {/* Additional info */}
              {result && (
                <div className="bg-white border border-gray-200 rounded-xl p-5">
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 text-sm">
                    <div>
                      <p className="text-gray-500">Confidence level</p>
                      <p className="font-semibold text-gray-900">{(result.confidence_level * 100).toFixed(0)}%</p>
                    </div>
                    <div>
                      <p className="text-gray-500">Statistical power</p>
                      <p className="font-semibold text-gray-900">{(result.power * 100).toFixed(0)}%</p>
                    </div>
                    <div>
                      <p className="text-gray-500">Variants</p>
                      <p className="font-semibold text-gray-900">{result.n_variants}</p>
                    </div>
                    <div>
                      <p className="text-gray-500">Test type</p>
                      <p className="font-semibold text-gray-900">{result.two_tailed ? 'Two-tailed' : 'One-tailed'}</p>
                    </div>
                  </div>
                </div>
              )}

              {/* Power Curve Chart */}
              <div className="bg-white border border-gray-200 rounded-xl p-5">
                <h2 className="text-sm font-semibold text-gray-700 mb-1">
                  Power Curve
                </h2>
                <p className="text-xs text-gray-400 mb-4">
                  Sample size required per variant vs. relative effect size. Larger effects are easier to detect.
                </p>

                {chartData.length > 0 ? (
                  <ResponsiveContainer width="100%" height={220}>
                    <LineChart data={chartData} margin={{ top: 5, right: 20, left: 10, bottom: 5 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#f3f4f6" />
                      <XAxis
                        dataKey="effectPct"
                        tickFormatter={(v) => `${v}%`}
                        tick={{ fontSize: 11, fill: '#9ca3af' }}
                        label={{ value: 'Relative Effect Size', position: 'insideBottomRight', offset: -5, fontSize: 11, fill: '#9ca3af' }}
                      />
                      <YAxis
                        tickFormatter={(v) => v >= 1000 ? `${(v / 1000).toFixed(0)}k` : v}
                        tick={{ fontSize: 11, fill: '#9ca3af' }}
                        label={{ value: 'n per variant', angle: -90, position: 'insideLeft', fontSize: 11, fill: '#9ca3af' }}
                      />
                      <Tooltip
                        formatter={(v: unknown) => fmtNumber(v as number)}
                        labelFormatter={(l) => `Effect: ${l}%`}
                      />
                      <Line
                        type="monotone"
                        dataKey="sampleSize"
                        stroke="#2563eb"
                        strokeWidth={2}
                        dot={false}
                      />
                      {targetPoint && (
                        <ReferenceDot
                          x={targetPoint.effectPct}
                          y={targetPoint.sampleSize}
                          r={6}
                          fill="#2563eb"
                          stroke="white"
                          strokeWidth={2}
                          label={{
                            value: `MDE target`,
                            position: 'top',
                            fontSize: 10,
                            fill: '#2563eb',
                          }}
                        />
                      )}
                    </LineChart>
                  </ResponsiveContainer>
                ) : (
                  <div className="h-48 flex items-center justify-center text-gray-400 text-sm">
                    {loading ? 'Computing...' : 'Adjust parameters above to see the power curve.'}
                  </div>
                )}
              </div>

              {/* AI Planning Advice */}
              <div className="bg-white border border-gray-200 rounded-xl p-5">
                <h2 className="text-sm font-semibold text-gray-700 mb-1">
                  AI Planning Advice
                </h2>
                <p className="text-xs text-gray-400 mb-4">
                  Get plain-English interpretation and suggestions for your experiment.
                  Uses Claude AI when available, falls back to built-in templates.
                </p>

                <div className="space-y-3 mb-4">
                  <div>
                    <label className="block text-xs font-medium text-gray-600 mb-1">
                      Experiment Name (optional)
                    </label>
                    <input
                      type="text"
                      placeholder="e.g. Checkout CTA Button Test"
                      value={experimentName}
                      onChange={(e) => setExperimentName(e.target.value)}
                      className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm text-gray-700 focus:ring-2 focus:ring-blue-500 focus:border-transparent outline-none"
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-medium text-gray-600 mb-1">
                      Primary Metric (optional)
                    </label>
                    <input
                      type="text"
                      placeholder="e.g. checkout conversion rate"
                      value={metricDescription}
                      onChange={(e) => setMetricDescription(e.target.value)}
                      className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm text-gray-700 focus:ring-2 focus:ring-blue-500 focus:border-transparent outline-none"
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-medium text-gray-600 mb-1">
                      Business Context (optional)
                    </label>
                    <textarea
                      placeholder="e.g. Q4 launch, mobile-only traffic segment"
                      value={businessContext}
                      onChange={(e) => setBusinessContext(e.target.value)}
                      rows={2}
                      className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm text-gray-700 focus:ring-2 focus:ring-blue-500 focus:border-transparent outline-none resize-none"
                    />
                  </div>
                </div>

                <button
                  onClick={getAdvice}
                  disabled={adviceLoading || !result}
                  className="bg-blue-600 text-white px-5 py-2.5 rounded-lg text-sm font-medium hover:bg-blue-700 transition disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {adviceLoading ? 'Generating advice...' : 'Get AI Advice'}
                </button>

                {adviceError && (
                  <p className="text-xs text-red-600 mt-2">{adviceError}</p>
                )}

                {advice && (
                  <div className="mt-4 bg-blue-50 rounded-lg p-4">
                    <div className="flex items-center gap-2 mb-2">
                      <span className="text-xs font-medium text-blue-700 uppercase tracking-wide">
                        {advice.generated_by === 'ai' ? 'AI-generated advice' : 'Template advice'}
                      </span>
                      {advice.generated_by === 'ai' && (
                        <span className="text-xs bg-blue-100 text-blue-700 px-2 py-0.5 rounded-full">
                          Claude AI
                        </span>
                      )}
                    </div>
                    <pre className="text-sm text-gray-700 whitespace-pre-wrap font-sans leading-relaxed">
                      {advice.advice}
                    </pre>
                  </div>
                )}
              </div>

              {/* Learn more */}
              <div className="bg-gray-50 border border-gray-200 rounded-xl p-4 flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium text-gray-700">Want to understand the math?</p>
                  <p className="text-xs text-gray-500">Read our statistics guide on power analysis, MDE, and alpha.</p>
                </div>
                <Link
                  href="/docs/statistics/power-analysis"
                  className="text-blue-600 text-sm font-medium hover:text-blue-700 transition whitespace-nowrap ml-4"
                >
                  Read the guide
                </Link>
              </div>

            </div>
          </div>
        </div>
      </div>
    </>
  );
}
