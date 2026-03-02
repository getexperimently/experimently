import React, { useState } from 'react';
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from 'recharts';
import { VariantTimeSeries } from '@/types/results';

interface TrendChartProps {
  series: VariantTimeSeries[];
}

type ViewMode = 'cumulative' | 'daily';

const CONTROL_COLOR = '#3b82f6';
const VARIANT_COLORS = ['#10b981', '#f59e0b', '#ef4444', '#8b5cf6'];

export function TrendChart({ series }: TrendChartProps) {
  const [viewMode, setViewMode] = useState<ViewMode>('cumulative');

  if (!series.length) {
    return (
      <div
        className="flex items-center justify-center h-48 text-slate-500"
        data-testid="trend-empty"
      >
        No trend data available
      </div>
    );
  }

  // Collect all unique dates across all series
  const allDates = Array.from(
    new Set(
      series.flatMap((s) =>
        (viewMode === 'cumulative' ? s.cumulative : s.values).map((d) => d.date)
      )
    )
  ).sort();

  // Merge into one array: { date, [variantId]: mean }
  const chartData = allDates.map((date) => {
    const point: Record<string, string | number> = { date };
    series.forEach((s) => {
      const dataPoints = viewMode === 'cumulative' ? s.cumulative : s.values;
      const dp = dataPoints.find((d) => d.date === date);
      if (dp !== undefined) {
        point[s.variant_id] = dp.mean;
      }
    });
    return point;
  });

  return (
    <div className="w-full" data-testid="trend-chart">
      <div className="flex justify-end mb-2 gap-2">
        <button
          onClick={() => setViewMode('cumulative')}
          className={`px-3 py-1 text-sm rounded ${
            viewMode === 'cumulative'
              ? 'bg-blue-600 text-white'
              : 'bg-slate-100 text-slate-700 hover:bg-slate-200'
          }`}
          aria-pressed={viewMode === 'cumulative'}
        >
          Cumulative
        </button>
        <button
          onClick={() => setViewMode('daily')}
          className={`px-3 py-1 text-sm rounded ${
            viewMode === 'daily'
              ? 'bg-blue-600 text-white'
              : 'bg-slate-100 text-slate-700 hover:bg-slate-200'
          }`}
          aria-pressed={viewMode === 'daily'}
        >
          Daily
        </button>
      </div>
      <div className="h-72">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart
            data={chartData}
            margin={{ top: 20, right: 30, left: 20, bottom: 5 }}
          >
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="date" tick={{ fontSize: 11 }} />
            <YAxis tickFormatter={(v: number) => `${(v * 100).toFixed(1)}%`} />
            <Tooltip
              formatter={(v) => [`${((v as number) * 100).toFixed(2)}%`, '']}
            />
            <Legend />
            {series.map((s, idx) => (
              <Line
                key={s.variant_id}
                dataKey={s.variant_id}
                name={s.variant_name}
                stroke={
                  s.is_control
                    ? CONTROL_COLOR
                    : VARIANT_COLORS[(idx - 1) % VARIANT_COLORS.length]
                }
                dot={false}
                connectNulls
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
