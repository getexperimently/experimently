#!/usr/bin/env node
/**
 * Remove the dashboard from a marketing build's static export.
 *
 * `next build` with `output: 'export'` writes every page under `out/`. The
 * public site has no API behind it, so `/experiments`, `/feature-flags`,
 * `/admin/*`, `/results`, `/workspaces` and `/login` are shells that can never
 * load anything -- `POST /api/v1/auth/login` returns the site's own HTML with
 * a 404 status. Shipping them makes the project look broken to exactly the
 * people evaluating it.
 *
 *   node scripts/prune-marketing-site.mjs [outDir]     (default: out)
 *
 * It REFUSES to run unless NEXT_PUBLIC_SITE_MODE=marketing, so it cannot
 * quietly delete the dashboard out of a platform build -- which is the failure
 * that would matter, and the one a `rm -rf` in a deploy script invites.
 *
 * It also refuses when nothing matched. A prune that removes nothing has
 * either been pointed at the wrong directory or is out of step with the route
 * list, and both are worth a loud failure rather than a silent success. That
 * is the same reasoning as the vacuity guards in the docs sweeps.
 */
import { existsSync, rmSync, readdirSync, statSync } from 'node:fs';
import { join, resolve } from 'node:path';

const PLATFORM_ONLY = [
  'admin',
  'experiments',
  'feature-flags',
  'results',
  'workspaces',
  'login',
];

// Kept deliberately: both work with no backend.
const KEEP = ['docs', 'power-calculator'];

const outDir = resolve(process.argv[2] ?? 'out');

if (process.env.NEXT_PUBLIC_SITE_MODE !== 'marketing') {
  console.error(
    'prune-marketing-site: refusing to run.\n' +
    '  NEXT_PUBLIC_SITE_MODE is ' +
    `${JSON.stringify(process.env.NEXT_PUBLIC_SITE_MODE ?? null)}, not "marketing".\n` +
    '  This deletes the dashboard; it must only ever run against a build that\n' +
    '  was made without one.',
  );
  process.exit(1);
}

if (!existsSync(outDir)) {
  console.error(`prune-marketing-site: ${outDir} does not exist. Run \`next build\` first.`);
  process.exit(1);
}

let removed = 0;
const removedNames = [];

for (const name of PLATFORM_ONLY) {
  // Both shapes: a directory (`out/experiments/index.html`) and the flat file
  // (`out/experiments.html`) Next writes for a page with no dynamic children.
  for (const candidate of [join(outDir, name), join(outDir, `${name}.html`)]) {
    if (!existsSync(candidate)) continue;
    rmSync(candidate, { recursive: true, force: true });
    removed += 1;
    removedNames.push(candidate.slice(outDir.length + 1));
  }
}

if (removed === 0) {
  console.error(
    `prune-marketing-site: removed nothing from ${outDir}.\n` +
    '  Either the directory is wrong or the route list is out of date. A prune\n' +
    '  that silently removes nothing is worse than one that fails.',
  );
  process.exit(1);
}

// What survived, so the log says what the public site actually is.
const survivors = readdirSync(outDir)
  .filter((n) => !n.startsWith('_') && !n.startsWith('.'))
  .filter((n) => statSync(join(outDir, n)).isDirectory() || n.endsWith('.html'))
  .sort();

console.log(`prune-marketing-site: removed ${removed} path(s) from ${outDir}`);
for (const n of removedNames) console.log(`  - ${n}`);
console.log('remaining:');
for (const n of survivors) console.log(`  ${n}`);

const leaked = PLATFORM_ONLY.filter(
  (n) => existsSync(join(outDir, n)) || existsSync(join(outDir, `${n}.html`)),
);
if (leaked.length) {
  console.error(`prune-marketing-site: these survived and should not have: ${leaked.join(', ')}`);
  process.exit(1);
}

const missing = KEEP.filter(
  (n) => !existsSync(join(outDir, n)) && !existsSync(join(outDir, `${n}.html`)),
);
if (missing.length) {
  console.error(
    `prune-marketing-site: these should have survived and did not: ${missing.join(', ')}.\n` +
    '  The public site needs them; something removed too much.',
  );
  process.exit(1);
}
