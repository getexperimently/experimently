import { modulePageStub } from '@/components/ModuleNotice';
import { MODULES } from '@/services/modules';

export default modulePageStub({
  title: 'Single sign-on',
  module: MODULES.SSO,
  description: 'Sign in with your organisation’s identity provider (Okta, Google, GitHub).',
});
