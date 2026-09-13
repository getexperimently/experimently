import { modulePageStub } from '@/components/ModuleNotice';
import { MODULES } from '@/services/modules';

export default modulePageStub({
  title: 'Workspace API Keys',
  module: MODULES.WORKSPACES,
  description: 'Issue API keys scoped to a single workspace rather than the whole instance.',
});
