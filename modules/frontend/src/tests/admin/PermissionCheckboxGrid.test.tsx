import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import { PermissionCheckboxGrid } from '@modules/components/admin/roles/PermissionCheckboxGrid';

const ALL_PERMISSIONS = [
  'experiments:read',
  'experiments:create',
  'experiments:update',
  'experiments:delete',
  'feature_flags:read',
  'feature_flags:create',
  'feature_flags:update',
  'feature_flags:delete',
  'users:read',
  'users:create',
  'users:update',
  'users:delete',
  'audit_logs:read',
  'safety:read',
  'safety:update',
  'rbac:read',
  'rbac:manage',
];

describe('PermissionCheckboxGrid', () => {
  it('renders all permission categories', () => {
    render(
      <PermissionCheckboxGrid
        selectedPermissions={[]}
        onChange={jest.fn()}
      />
    );
    expect(screen.getByText(/experiments/i)).toBeInTheDocument();
    expect(screen.getByText(/feature_flags/i)).toBeInTheDocument();
    expect(screen.getByText(/users/i)).toBeInTheDocument();
    expect(screen.getByText(/audit_logs/i)).toBeInTheDocument();
    expect(screen.getByText(/safety/i)).toBeInTheDocument();
    expect(screen.getByText(/rbac/i)).toBeInTheDocument();
  });

  it('renders individual permission checkboxes', () => {
    render(
      <PermissionCheckboxGrid
        selectedPermissions={[]}
        onChange={jest.fn()}
      />
    );
    const checkboxes = screen.getAllByRole('checkbox');
    expect(checkboxes.length).toBe(ALL_PERMISSIONS.length);
  });

  it('checked state matches selectedPermissions prop', () => {
    const selected = ['experiments:read', 'users:read'];
    render(
      <PermissionCheckboxGrid
        selectedPermissions={selected}
        onChange={jest.fn()}
      />
    );
    const readExperimentsCheckbox = screen.getByTestId('permission-checkbox-experiments:read');
    const createExperimentsCheckbox = screen.getByTestId('permission-checkbox-experiments:create');
    const readUsersCheckbox = screen.getByTestId('permission-checkbox-users:read');

    expect(readExperimentsCheckbox).toBeChecked();
    expect(createExperimentsCheckbox).not.toBeChecked();
    expect(readUsersCheckbox).toBeChecked();
  });

  it('clicking a checkbox calls onChange with updated permissions array', () => {
    const onChange = jest.fn();
    render(
      <PermissionCheckboxGrid
        selectedPermissions={[]}
        onChange={onChange}
      />
    );
    const checkbox = screen.getByTestId('permission-checkbox-experiments:read');
    fireEvent.click(checkbox);
    expect(onChange).toHaveBeenCalledTimes(1);
  });

  it('checking a permission adds it to the array', () => {
    const onChange = jest.fn();
    render(
      <PermissionCheckboxGrid
        selectedPermissions={[]}
        onChange={onChange}
      />
    );
    const checkbox = screen.getByTestId('permission-checkbox-experiments:read');
    fireEvent.click(checkbox);
    expect(onChange).toHaveBeenCalledWith(
      expect.arrayContaining(['experiments:read'])
    );
  });

  it('unchecking a permission removes it from the array', () => {
    const onChange = jest.fn();
    render(
      <PermissionCheckboxGrid
        selectedPermissions={['experiments:read', 'users:read']}
        onChange={onChange}
      />
    );
    const checkbox = screen.getByTestId('permission-checkbox-experiments:read');
    fireEvent.click(checkbox);
    const result = onChange.mock.calls[0][0] as string[];
    expect(result).not.toContain('experiments:read');
    expect(result).toContain('users:read');
  });

  it('renders read-only when readOnly=true (checkboxes disabled)', () => {
    render(
      <PermissionCheckboxGrid
        selectedPermissions={['experiments:read']}
        onChange={jest.fn()}
        readOnly={true}
      />
    );
    const checkboxes = screen.getAllByRole('checkbox');
    checkboxes.forEach((checkbox) => {
      expect(checkbox).toBeDisabled();
    });
  });

  it('renders with data-testid="permission-checkbox-grid"', () => {
    render(
      <PermissionCheckboxGrid
        selectedPermissions={[]}
        onChange={jest.fn()}
      />
    );
    expect(screen.getByTestId('permission-checkbox-grid')).toBeInTheDocument();
  });
});
