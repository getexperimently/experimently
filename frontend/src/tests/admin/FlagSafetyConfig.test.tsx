import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import { FlagSafetyConfig } from '@/components/admin/safety/FlagSafetyConfig';

describe('FlagSafetyConfig', () => {
  const props = {
    flagId: 'flag-123',
    flagName: 'dark-mode',
    onClose: jest.fn(),
  };

  beforeEach(() => {
    props.onClose.mockClear();
  });

  it('renders with flag name and ID', () => {
    render(<FlagSafetyConfig {...props} />);
    expect(screen.getByTestId('flag-safety-config')).toBeInTheDocument();
    expect(screen.getByText(/Safety Config: dark-mode/)).toBeInTheDocument();
    expect(screen.getByText('flag-123')).toBeInTheDocument();
  });

  it('displays the flag name in monospace', () => {
    render(<FlagSafetyConfig {...props} />);
    const flagNameEl = screen.getByText('dark-mode');
    expect(flagNameEl.className).toContain('font-mono');
  });

  it('calls onClose when close button is clicked', () => {
    render(<FlagSafetyConfig {...props} />);
    fireEvent.click(screen.getByTestId('flag-safety-config-close'));
    expect(props.onClose).toHaveBeenCalledTimes(1);
  });

  it('has accessible close button', () => {
    render(<FlagSafetyConfig {...props} />);
    expect(screen.getByLabelText('Close')).toBeInTheDocument();
  });
});
