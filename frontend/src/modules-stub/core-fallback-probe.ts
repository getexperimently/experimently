/**
 * A module that exists **only** in the stub tree.
 *
 * It stands in for every `@modules/*` import once `modules/frontend/src/` has
 * been deleted from a core build: resolving `@modules/core-fallback-probe` can
 * only succeed by falling through to `src/modules-stub/`.
 * `src/tests/modules-alias.test.ts` asserts that it resolves in jest and
 * `tsconfig.core.json` type-checks it, which is how the alias fallback is
 * proven in two of the three toolchains without deleting anything. The third
 * (webpack) is proven by an actual `EXPERIMENTLY_PROFILE=core next build`.
 *
 * Do not add a `modules/frontend/src/core-fallback-probe.ts`; that would make
 * the probe pass for the wrong reason.
 */
export const RESOLVED_FROM = 'modules-stub';

export default RESOLVED_FROM;
