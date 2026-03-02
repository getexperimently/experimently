import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import { AuditLogFilter } from '@/components/admin/audit/AuditLogFilter';

describe('AuditLogFilter', () => {
  const defaultFilters = {};
  const mockOnFilterChange = jest.fn();

  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('renders all filter inputs (action_type, entity_type, user email, date range)', () => {
    render(<AuditLogFilter filters={defaultFilters} onFilterChange={mockOnFilterChange} />);
    expect(screen.getByTestId('filter-action-type')).toBeInTheDocument();
    expect(screen.getByTestId('filter-entity-type')).toBeInTheDocument();
    expect(screen.getByTestId('filter-user-email')).toBeInTheDocument();
    expect(screen.getByTestId('filter-start-date')).toBeInTheDocument();
    expect(screen.getByTestId('filter-end-date')).toBeInTheDocument();
  });

  it('calls onFilterChange when action_type select changes', () => {
    render(<AuditLogFilter filters={defaultFilters} onFilterChange={mockOnFilterChange} />);
    fireEvent.change(screen.getByTestId('filter-action-type'), {
      target: { value: 'toggle_enable' },
    });
    expect(mockOnFilterChange).toHaveBeenCalledWith(
      expect.objectContaining({ action_type: 'toggle_enable' })
    );
  });

  it('calls onFilterChange when entity_type select changes', () => {
    render(<AuditLogFilter filters={defaultFilters} onFilterChange={mockOnFilterChange} />);
    fireEvent.change(screen.getByTestId('filter-entity-type'), {
      target: { value: 'feature_flag' },
    });
    expect(mockOnFilterChange).toHaveBeenCalledWith(
      expect.objectContaining({ entity_type: 'feature_flag' })
    );
  });

  it('calls onFilterChange when user email input changes', () => {
    render(<AuditLogFilter filters={defaultFilters} onFilterChange={mockOnFilterChange} />);
    fireEvent.change(screen.getByTestId('filter-user-email'), {
      target: { value: 'test@example.com' },
    });
    expect(mockOnFilterChange).toHaveBeenCalledWith(
      expect.objectContaining({ user_email: 'test@example.com' })
    );
  });

  it('calls onFilterChange when start_date changes', () => {
    render(<AuditLogFilter filters={defaultFilters} onFilterChange={mockOnFilterChange} />);
    fireEvent.change(screen.getByTestId('filter-start-date'), {
      target: { value: '2024-01-01' },
    });
    expect(mockOnFilterChange).toHaveBeenCalledWith(
      expect.objectContaining({ start_date: '2024-01-01' })
    );
  });

  it('calls onFilterChange when end_date changes', () => {
    render(<AuditLogFilter filters={defaultFilters} onFilterChange={mockOnFilterChange} />);
    fireEvent.change(screen.getByTestId('filter-end-date'), {
      target: { value: '2024-01-31' },
    });
    expect(mockOnFilterChange).toHaveBeenCalledWith(
      expect.objectContaining({ end_date: '2024-01-31' })
    );
  });

  it('"Clear Filters" button resets all filters and calls onFilterChange with empty object', () => {
    const filtersWithValues = {
      action_type: 'toggle_enable',
      entity_type: 'feature_flag',
      user_email: 'test@example.com',
      start_date: '2024-01-01',
      end_date: '2024-01-31',
    };
    render(<AuditLogFilter filters={filtersWithValues} onFilterChange={mockOnFilterChange} />);
    fireEvent.click(screen.getByTestId('clear-filters-button'));
    expect(mockOnFilterChange).toHaveBeenCalledWith({});
  });

  it('renders with data-testid="audit-log-filter"', () => {
    render(<AuditLogFilter filters={defaultFilters} onFilterChange={mockOnFilterChange} />);
    expect(screen.getByTestId('audit-log-filter')).toBeInTheDocument();
  });
});
