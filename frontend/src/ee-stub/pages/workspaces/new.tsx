import { enterprisePageStub } from '@/components/EnterpriseFeatureNotice';
import { FEATURES } from '@/services/edition';

export default enterprisePageStub({
  title: 'New Workspace',
  feature: FEATURES.WORKSPACES,
  description: 'Separate teams into workspaces, each with its own members, experiments, flags and API keys.',
});
