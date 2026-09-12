/**
 * The `@ee/*` alias — one rule, shared by every toolchain.
 *
 * `@ee/x` resolves to `src/ee/x` in an Enterprise tree and to `src/ee-stub/x`
 * in a Community one, so an Enterprise route can be a one-line re-export that
 * compiles either way.
 *
 *   Enterprise  ⟺  EXPERIMENTLY_EDITION is not "ce"  AND  src/ee exists
 *
 * `scripts/community_build.sh` deletes `src/ee`, so a Community build gets the
 * stubs without setting anything; `EXPERIMENTLY_EDITION=ce` forces the same
 * resolution on an undeleted tree, which is how it is tested.
 *
 * Consumers:
 *   next.config.js   → webpack `resolve.alias` (+ `typescript.tsconfigPath`)
 *   jest.config.js   → `moduleNameMapper`
 *   tsconfig.json    → `paths` (real first, stub as fallback)
 *   tsconfig.ce.json → `paths` (stub only) — what a Community `tsc` uses
 */
const fs = require('fs');
const path = require('path');

const EE_DIR = path.join(__dirname, 'src', 'ee');
const EE_STUB_DIR = path.join(__dirname, 'src', 'ee-stub');

/** True when the Enterprise module tree should be used. */
function enterpriseTreeAvailable(env = process.env) {
  if (String(env.EXPERIMENTLY_EDITION || '').toLowerCase() === 'ce') return false;
  return fs.existsSync(EE_DIR);
}

/** Directories `@ee/*` resolves against, in order. */
function eeAliasTargets(env = process.env) {
  return enterpriseTreeAvailable(env) ? [EE_DIR, EE_STUB_DIR] : [EE_STUB_DIR];
}

module.exports = {
  EE_DIR,
  EE_STUB_DIR,
  enterpriseTreeAvailable,
  eeAliasTargets,
};
