/**
 * Enterprise route — workspace list (EP-057).
 *
 * Thin re-export so this file compiles in both editions: `@ee/*` resolves to
 * `src/ee/` when the Enterprise tree is present and to `src/ee-stub/`
 * (an "Enterprise feature" notice) when it is not. See `next.config.js`.
 */
export { default } from '@ee/pages/workspaces/index';
