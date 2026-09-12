/**
 * A module that exists **only** in the stub tree.
 *
 * It stands in for every `@ee/*` import once `src/ee/` has been deleted from a
 * Community build: resolving `@ee/ce-fallback-probe` can only succeed by
 * falling through to `src/ee-stub/`. `src/tests/ee-alias.test.ts` asserts that
 * it resolves in jest and `tsconfig.ce.json` type-checks it, which is how the
 * alias fallback is proven in two of the three toolchains without deleting
 * anything. The third (webpack) is proven by an actual
 * `EXPERIMENTLY_EDITION=ce next build`.
 *
 * Do not add a `src/ee/ce-fallback-probe.ts`; that would make the probe pass
 * for the wrong reason.
 */
export const RESOLVED_FROM = 'ee-stub';

export default RESOLVED_FROM;
