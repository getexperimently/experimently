import { modulePageStub } from '@/components/ModuleNotice';
import { MODULES } from '@/services/modules';

export default modulePageStub({
  title: 'Workspace',
  module: MODULES.WORKSPACES,
  description: 'Separate teams into workspaces, each with its own members, experiments, flags and API keys.',
});
