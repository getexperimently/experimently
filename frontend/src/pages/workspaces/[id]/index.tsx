/**
 * Module route — workspace overview (EP-057).
 *
 * Thin re-export so this file compiles in both profiles: `@modules/*` resolves
 * to `modules/frontend/src/` when the modules tree is present and to
 * `src/modules-stub/` (a "module not installed" notice) when it is not. See
 * `next.config.js`.
 */
export { default } from '@modules/pages/workspaces/[id]/index';
