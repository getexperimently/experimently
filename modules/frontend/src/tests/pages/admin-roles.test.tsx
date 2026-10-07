/**
 * /admin/roles says that custom roles and direct permission grants do not
 * change what a user can do yet (#891): no permission check reads them, and
 * each user's built-in role decides.
 */
import React from 'react';
import { render, screen } from '@testing-library/react';
import { RoleManagementPage } from '@modules/pages/admin/roles';
import { RbacService } from '@modules/rbac';

jest.mock('@modules/rbac');

jest.mock('@/components/admin/AdminLayout', () => ({
  AdminLayout: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

const mockListRoles = RbacService.listRoles as jest.Mock;

describe('RoleManagementPage', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockListRoles.mockResolvedValue([]);
  });

  it('says that custom roles and direct grants are recorded and do not change access yet', async () => {
    render(<RoleManagementPage />);
    expect(screen.getByTestId('roles-access-note')).toHaveTextContent(
      "Custom roles and direct permission grants are recorded, but they do not change what anyone can do yet: each user's built-in role decides."
    );
    // The page loaded its table, so the note is shown with it, not instead of it.
    expect(await screen.findByText('No custom roles found')).toBeInTheDocument();
    expect(mockListRoles).toHaveBeenCalledTimes(1);
  });
});
