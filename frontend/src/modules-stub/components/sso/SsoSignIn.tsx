/**
 * Core-profile stand-in for `@modules/components/sso/SsoSignIn`: a core build
 * has no SSO, so the login page shows no SSO button and reads no `sso_error`.
 */
export interface SsoSignInProps {
  nextPath: string;
  onError: (message: string | null, retry: (() => void) | null) => void;
  rateLimitedMessage: string;
  unreachableMessage: () => string;
}

export default function SsoSignIn(_props: SsoSignInProps): null {
  return null;
}
