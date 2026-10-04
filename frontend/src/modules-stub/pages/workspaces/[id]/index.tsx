import { modulePageStub } from '@/components/ModuleNotice';
import { MODULES } from '@/services/modules';

export default modulePageStub({
  title: 'Workspace',
  module: MODULES.WORKSPACES,
  description: 'Separate teams into workspaces with workspace roles and invites. Access to experiments and flags is by platform role.',
});
