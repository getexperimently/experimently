import React from 'react';
import { render, waitFor } from '@testing-library/react';
import PowerCalculatorPage from '@/pages/power-calculator';

jest.mock('next/head', () => { const H=({children}:{children:React.ReactNode})=><>{children}</>; H.displayName='H'; return H; });
jest.mock('next/router', () => ({ useRouter: () => ({ pathname:'/power-calculator', query:{}, push:jest.fn(), replace:jest.fn(), isReady:true }) }));

it('renders a real sample size with NO api reachable', async () => {
  // Every fetch fails, as on the published site where /api/v1/* 404s.
  global.fetch = jest.fn(() => Promise.reject(new Error('no API'))) as unknown as typeof fetch;
  render(<PowerCalculatorPage />);
  // defaults: baseline 0.05, mde 0.10, alpha 0.05, power 0.80, k=2 -> 31234
  await waitFor(() => {
    expect(document.body.textContent).toMatch(/31,?234/);
  }, { timeout: 4000 });
});
