/**
 * Routes rendered without the application shell. `/sso/complete` is one so
 * that it is never `protected`: RequireAuth would bounce an anonymous visitor
 * to `/login?next=`, carrying the SSO hand-off fragment along (C2b).
 */
const BARE_ROUTES = new Set<string>(['/login', '/', '/sso/complete']);

/**
 * Routes inside the shell that do not require a session. The API is still the
 * enforcement point; these pages are either static or call public endpoints
 * (the power calculator).
 */
const OPEN_ROUTE_PREFIXES = ['/docs', '/power-calculator', '/404', '/500', '/_error'];

export type RouteKind = 'bare' | 'open' | 'protected';

/**
 * Classify a Next.js route pattern (`router.pathname`, e.g. `/experiments/[id]`).
 */
export function routeKind(pathname: string): RouteKind {
  if (BARE_ROUTES.has(pathname)) return 'bare';
  if (OPEN_ROUTE_PREFIXES.some((p) => pathname === p || pathname.startsWith(`${p}/`))) {
    return 'open';
  }
  return 'protected';
}
