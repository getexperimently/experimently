import { enterprisePageStub } from '@/components/EnterpriseFeatureNotice';
import { FEATURES } from '@/services/edition';

export default enterprisePageStub({
  title: 'Workspace Members',
  feature: FEATURES.WORKSPACES,
  description: 'Invite people to a workspace and manage what each of them may do in it.',
});
