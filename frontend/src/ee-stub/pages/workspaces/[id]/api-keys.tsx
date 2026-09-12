import { enterprisePageStub } from '@/components/EnterpriseFeatureNotice';
import { FEATURES } from '@/services/edition';

export default enterprisePageStub({
  title: 'Workspace API Keys',
  feature: FEATURES.WORKSPACES,
  description: 'Issue API keys scoped to a single workspace rather than the whole instance.',
});
