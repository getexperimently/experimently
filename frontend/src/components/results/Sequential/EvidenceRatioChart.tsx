import React from 'react';
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ReferenceLine,
  ResponsiveContainer,
  Legend,
} from 'recharts';
import { EvidencePoint } from '@/types/sequential';

interface EvidenceRatioChartProps {
  trajectory: EvidencePoint[];
  boundary: number;
}

export function EvidenceRatioChart({
  trajectory,
  boundary,
}: EvidenceRatioChartProps) {
  if (!trajectory.length) {
    return (
      <div
        data-testid="evidence-chart-empty"
        className="text-center py-12 text-slate-500 text-sm"
      >
        No evidence data available yet
      </div>
    );
  }

  const data = trajectory.map((point) => ({
    sampleSize: point.sample_size,
    lambdaRatio: point.lambda_ratio,
    pValue: point.always_valid_p_value,
    canStop: point.can_stop,
  }));

  return (
    <div data-testid="evidence-ratio-chart" className="w-full">
      <ResponsiveContainer width="100%" height={320}>
        <LineChart data={data} margin={{ top: 8, right: 24, left: 8, bottom: 8 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
          <XAxis
            dataKey="sampleSize"
            label={{ value: 'Sample Size', position: 'insideBottomRight', offset: -4 }}
            tick={{ fontSize: 12 }}
          />
          <YAxis
            label={{
              value: 'Lambda Ratio',
              angle: -90,
              position: 'insideLeft',
              offset: 10,
            }}
            tick={{ fontSize: 12 }}
          />
          <Tooltip
            formatter={(value: number, name: string) => {
              if (name === 'Lambda Ratio') return [value.toFixed(3), name];
              return [value, name];
            }}
            labelFormatter={(label: number) => `Sample size: ${label}`}
          />
          <Legend />
          <ReferenceLine
            y={boundary}
            stroke="#ef4444"
            strokeDasharray="5 5"
            label={{ value: `Boundary (${boundary.toFixed(1)})`, fill: '#ef4444', fontSize: 11 }}
          />
          <ReferenceLine
            y={1}
            stroke="#94a3b8"
            strokeDasharray="2 2"
          />
          <Line
            type="monotone"
            dataKey="lambdaRatio"
            name="Lambda Ratio"
            stroke="#3b82f6"
            strokeWidth={2}
            dot={false}
            activeDot={{ r: 4 }}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
