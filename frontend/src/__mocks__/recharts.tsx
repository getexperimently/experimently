import React from 'react';


export const ResponsiveContainer = ({ children }: any) => (
  <div data-testid="responsive-container">{children}</div>
);


export const BarChart = ({ children }: any) => (
  <div data-testid="bar-chart">{children}</div>
);


export const Bar = ({ name, children, 'data-is-control': dataIsControl, ...rest }: any) => (
  <div
    data-testid="variant-bar"
    data-is-control={dataIsControl}
    data-fill={rest.fill}
  >
    {String(name ?? '')}
    {children}
  </div>
);


export const LineChart = ({ children }: any) => (
  <div data-testid="line-chart">{children}</div>
);


export const Line = ({ name, children }: any) => (
  <div data-testid="trend-line">
    {String(name ?? '')}
    {children}
  </div>
);

export const XAxis = () => <div data-testid="x-axis" />;
export const YAxis = () => <div data-testid="y-axis" />;
export const CartesianGrid = () => <div />;
export const Tooltip = () => <div />;
export const Legend = () => <div />;
export const ErrorBar = () => <div />;
export const Cell = () => <div />;
export const ReferenceLine = () => <div />;
// Used by the power calculator's chart. Its absence made that page render as
// `undefined` under jest -- "Element type is invalid" -- which nothing caught
// because no test rendered the page until now.
export const ReferenceDot = () => <div />;
