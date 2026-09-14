import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import ResultsIndexPage from '@/pages/results/index';
import { formatPageTitle } from '@/components/PageTitle';
import { makeRouter } from './helpers/apiMock';

const mockRouter = makeRouter({ pathname: '/results', asPath: '/results' });
jest.mock('next/router', () => ({ useRouter: () => mockRouter }));

jest.mock('next/head', () => {
  const Head = ({ children }: { children: React.ReactNode }) => <>{children}</>;
  Head.displayName = 'MockHead';
  return Head;
});

describe('ResultsIndexPage (/results)', () => {
  beforeEach(() => {
    mockRouter.replace.mockClear();
  });

  it('replaces the route with /experiments on mount', async () => {
    render(<ResultsIndexPage />);
    await waitFor(() => expect(mockRouter.replace).toHaveBeenCalledWith('/experiments'));
    expect(mockRouter.replace).toHaveBeenCalledTimes(1);
  });

  it('renders a fallback link and the page title while redirecting', () => {
    // React 19 hoists <title> into document.head wherever it is rendered, so
    // the mocked passthrough Head above no longer leaves it in the container
    // for `screen` to find — `document.title` is where it lands, and saying so
    // is the stronger assertion anyway. Cleared first so a title left by the
    // test above cannot pass this one.
    document.title = '';
    render(<ResultsIndexPage />);
    expect(screen.getByTestId('results-redirect')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /experiments/i })).toHaveAttribute('href', '/experiments');
    expect(document.title).toBe(formatPageTitle('Results'));
  });
});
