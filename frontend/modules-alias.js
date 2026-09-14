/**
 * The `@modules/*` alias — one rule, shared by every toolchain.
 *
 * `@modules/x` resolves to `modules/frontend/src/x` (repository root, beside
 * this directory) in a full-profile tree and to `src/modules-stub/x` in a core
 * one, so a module route can be a one-line re-export that compiles either way.
 *
 *   full  ⟺  EXPERIMENTLY_PROFILE is not "core"  AND  modules/frontend/src exists
 *
 * The modules' dashboard code lives outside `frontend/` on purpose: `modules/`
 * is the optional part of the product, and `scripts/core_build.sh` deletes it
 * whole to prove the core profile builds, boots and passes its tests on its
 * own. A core build therefore gets the stubs without setting anything;
 * `EXPERIMENTLY_PROFILE=core` forces the same resolution on an undeleted
 * tree, which is how it is tested.
 *
 * Consumers:
 *   next.config.js      → Turbopack `turbopack.resolveAlias` (the default
 *                         bundler from Next 16) AND webpack `resolve.alias`
 *                         (`next build --webpack`), plus
 *                         `typescript.tsconfigPath`, `turbopack.root` and
 *                         `experimental.externalDir` so either bundler will
 *                         compile sources outside the project root
 *   jest.config.js      → `moduleNameMapper` + `roots` (module tests live
 *                         beside the modules)
 *   tsconfig.json       → `paths` (real first, stub as fallback) + `include`
 *   tsconfig.core.json  → `paths` (stub only) — what a core `tsc` uses
 *   Dockerfile          → `COPY modules/frontend/ /app/modules/frontend/` for
 *                         the full image; the core image never copies it
 *
 * One constraint the seam puts on the repository root: `<repo>/package.json`
 * must not declare `"type"`. It is the nearest package.json above
 * `modules/frontend/src`, and Turbopack reads the module format from it — an
 * explicit `"type": "commonjs"` there failed every file in the modules tree
 * with "Specified module format (CommonJs) is not matching the module format
 * of the source code (EcmaScript Modules)". Absent, the field defaults to
 * commonjs for Node exactly as before (the one root-level script,
 * tests/sdk-contract/test_js_sdk.js, is `require`-based), and Turbopack stops
 * treating the declaration as an instruction. The dashboard image never hit
 * this because it copies `frontend/` and `modules/frontend/` into `/app` with
 * no package.json between them. src/tests/modules-alias.test.ts pins it.
 */
const fs = require('fs');
const path = require('path');

/** Repository root: `frontend/` and `modules/` are siblings. */
const REPO_ROOT = path.resolve(__dirname, '..');
const MODULES_DIR = path.join(REPO_ROOT, 'modules', 'frontend', 'src');
const MODULES_STUB_DIR = path.join(__dirname, 'src', 'modules-stub');

/** True when the modules tree should be used (the full profile). */
function modulesTreeAvailable(env = process.env) {
  if (String(env.EXPERIMENTLY_PROFILE || '').toLowerCase() === 'core') return false;
  return fs.existsSync(MODULES_DIR);
}

/** Directories `@modules/*` resolves against, in order. */
function modulesAliasTargets(env = process.env) {
  return modulesTreeAvailable(env) ? [MODULES_DIR, MODULES_STUB_DIR] : [MODULES_STUB_DIR];
}

/**
 * The same rule spelled for Turbopack's `resolveAlias` — the bundler
 * `next build` uses by default from Next 16.
 *
 * Two differences from webpack's `resolve.alias`, both found by building:
 *
 *   1. webpack does prefix matching, so `'@modules': [dirs]` already covers
 *      `@modules/anything`. Turbopack matches the key whole unless it carries
 *      a `*`, and substitutes the captured tail into the `*` on the value
 *      side — so the key is `@modules/*` and every target ends in `/*`.
 *   2. A target is a module *request*, not a filesystem path: an absolute one
 *      is read as server-relative and re-rooted at the Next project directory
 *      ("aliased to server relative '/Users/…' inside of [project]/frontend",
 *      then Module not found). So the targets are `./`- and `../`-relative to
 *      this directory, which is that project directory.
 *
 * Same directories, same order as every other toolchain: the first that
 * contains the module wins, which is what makes a full tree fall back to the
 * stub for a module it does not carry.
 */
function modulesAliasTurbopack(env = process.env) {
  const request = (dir) => {
    const rel = path.relative(__dirname, dir).split(path.sep).join('/');
    return `${rel.startsWith('.') ? rel : `./${rel}`}/*`;
  };
  return { '@modules/*': modulesAliasTargets(env).map(request) };
}

module.exports = {
  REPO_ROOT,
  MODULES_DIR,
  MODULES_STUB_DIR,
  modulesTreeAvailable,
  modulesAliasTargets,
  modulesAliasTurbopack,
};
