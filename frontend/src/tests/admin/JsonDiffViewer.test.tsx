import React from 'react';
import { render, screen } from '@testing-library/react';
import { JsonDiffViewer } from '@/components/admin/audit/JsonDiffViewer';

describe('JsonDiffViewer', () => {
  it('renders nothing when both oldValue and newValue are null/undefined', () => {
    const { container } = render(<JsonDiffViewer oldValue={null} newValue={null} />);
    expect(container.firstChild).toBeNull();
  });

  it('renders old_value label when oldValue provided', () => {
    render(<JsonDiffViewer oldValue={{ enabled: false }} newValue={undefined} />);
    expect(screen.getByTestId('json-diff-viewer')).toBeInTheDocument();
    expect(screen.getByTestId('json-diff-old')).toBeInTheDocument();
  });

  it('renders new_value label when newValue provided', () => {
    render(<JsonDiffViewer oldValue={undefined} newValue={{ enabled: true }} />);
    expect(screen.getByTestId('json-diff-viewer')).toBeInTheDocument();
    expect(screen.getByTestId('json-diff-new')).toBeInTheDocument();
  });

  it('formats JSON objects with pretty-print (indented)', () => {
    const obj = { enabled: true, rollout: 50 };
    render(<JsonDiffViewer oldValue={undefined} newValue={obj} />);
    const newSection = screen.getByTestId('json-diff-new');
    expect(newSection.textContent).toContain(JSON.stringify(obj, null, 2));
  });

  it('handles string values (not just objects)', () => {
    render(<JsonDiffViewer oldValue="old-string" newValue="new-string" />);
    expect(screen.getByTestId('json-diff-old')).toBeInTheDocument();
    expect(screen.getByTestId('json-diff-new')).toBeInTheDocument();
    expect(screen.getByTestId('json-diff-old').textContent).toContain('old-string');
    expect(screen.getByTestId('json-diff-new').textContent).toContain('new-string');
  });

  it('renders with data-testid="json-diff-viewer"', () => {
    render(<JsonDiffViewer oldValue={{ a: 1 }} newValue={{ a: 2 }} />);
    expect(screen.getByTestId('json-diff-viewer')).toBeInTheDocument();
  });
});
