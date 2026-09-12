import { enterprisePageStub } from '@/components/EnterpriseFeatureNotice';
import { withAdminGuard } from '@/components/admin/withAdminGuard';
import { FEATURES } from '@/services/edition';

// Guarded like the page it stands in for: /admin/roles is an admin route in
// every edition, and the notice must not be the one admin page a VIEWER can
// open.
export default withAdminGuard(
  enterprisePageStub({
    title: 'Custom Roles',
    feature: FEATURES.RBAC,
    description: 'Define roles beyond the four built-in ones and grant permissions directly to a user.',
  }),
  { requiredRole: 'ADMIN' },
);
