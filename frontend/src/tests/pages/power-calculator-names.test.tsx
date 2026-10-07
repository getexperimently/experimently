/**
 * The Power Calculator's fields and figures have accessible names.
 *
 * Each control is named by its visible label alone: a screen reader says
 * "Baseline Conversion Rate", not "Baseline Conversion Rate 5.0%", and a test
 * or an assistive tool finds it by that label. The three figures are named
 * live regions (`<output>`, role status, aria-live polite): after the page
 * recalculates, a screen reader reads the new text of each figure that
 * changed, once, when it is idle. Before this, no control could be found by
 * its label and the figures were unnamed paragraphs.
 */
import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import PowerCalculatorPage from '@/pages/power-calculator';

jest.mock('next/head', () => { const H=({children}:{children:React.ReactNode})=><>{children}</>; H.displayName='H'; return H; });
jest.mock('next/router', () => ({ useRouter: () => ({ pathname:'/power-calculator', query:{}, push:jest.fn(), replace:jest.fn(), isReady:true }) }));

const CONTROLS: Array<[string, string]> = [
  ['Baseline Conversion Rate', 'slider'],
  ['Minimum Detectable Effect (relative)', 'slider'],
  ['Significance Level (alpha)', 'combobox'],
  ['Statistical Power', 'combobox'],
  ['Number of Variants (including control)', 'combobox'],
  ['Daily Users', 'spinbutton'],
  ['Traffic Allocation', 'slider'],
];

const FIGURES = ['Sample Size per Variant', 'MDE (absolute)', 'Estimated Runtime'];

describe('the power calculator names its fields and figures', () => {
  it.each(CONTROLS)('finds "%s" by its visible label alone', (label, role) => {
    render(<PowerCalculatorPage />);
    const byLabel = screen.getByLabelText(label);
    expect(screen.getByRole(role, { name: label })).toBe(byLabel);
  });

  it.each([
    ['Baseline Conversion Rate', '5.0%'],
    ['Minimum Detectable Effect (relative)', '10%'],
    ['Traffic Allocation', '100%'],
  ])('keeps the live value out of the name "%s", and still shows %s', (label, value) => {
    render(<PowerCalculatorPage />);
    const slider = screen.getByLabelText(label) as HTMLInputElement;
    // The accessible name is exactly the label: the value is not part of it ...
    expect(screen.getByRole('slider', { name: label })).toBe(slider);
    // ... and the label the reader sees still shows the value beside it.
    expect(slider.labels?.[0]?.textContent).toBe(`${label}${value}`);
  });

  it.each(FIGURES)('"%s" is a named polite live region', (name) => {
    render(<PowerCalculatorPage />);
    const figure = screen.getByRole('status', { name });
    expect(figure.tagName).toBe('OUTPUT');
    expect(figure).toHaveAttribute('aria-live', 'polite');
  });

  it('shows the per-variant sample size in its named figure, and follows a change', async () => {
    render(<PowerCalculatorPage />);
    const figure = screen.getByRole('status', { name: 'Sample Size per Variant' });
    // Defaults: baseline 0.05, MDE 10%, alpha 0.05, power 0.80, two variants.
    await waitFor(() => expect(figure).toHaveTextContent('31,234'), { timeout: 4000 });
    fireEvent.change(screen.getByLabelText('Statistical Power'), { target: { value: '0.9' } });
    // The same inputs at 90% power: POST /api/v1/power/sample-size answers 41813.
    await waitFor(() => expect(figure).toHaveTextContent('41,813'), { timeout: 4000 });
    expect(screen.getByRole('status', { name: 'MDE (absolute)' })).toHaveTextContent('+0.50%');
  });
});
