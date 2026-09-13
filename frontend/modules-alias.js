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
 *   next.config.js      → webpack `resolve.alias` (+ `typescript.tsconfigPath`,
 *                         `experimental.externalDir` so webpack will compile
 *                         sources outside the project root)
 *   jest.config.js      → `moduleNameMapper` + `roots` (module tests live
 *                         beside the modules)
 *   tsconfig.json       → `paths` (real first, stub as fallback) + `include`
 *   tsconfig.core.json  → `paths` (stub only) — what a core `tsc` uses
 *   Dockerfile          → `COPY modules/frontend/ /app/modules/frontend/` for
 *                         the full image; the core image never copies it
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

module.exports = {
  REPO_ROOT,
  MODULES_DIR,
  MODULES_STUB_DIR,
  modulesTreeAvailable,
  modulesAliasTargets,
};
