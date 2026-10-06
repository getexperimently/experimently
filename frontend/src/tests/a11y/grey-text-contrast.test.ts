/**
 * The grey secondary text on the pages the nightly accessibility audit scans
 * (login, experiments, feature flags, the admin shell) meets WCAG AA.
 *
 * Tailwind `slate-400` (#94a3b8) is 2.56:1 on white and 2.45:1 on `slate-50`,
 * under the 4.5:1 that small text needs; `slate-500` (#64748b) is 4.76:1 and
 * 4.55:1. The rendered check is `tests/e2e/accessibility.spec.ts`, which only
 * runs nightly; this is the pull-request-time pin on the same elements.
 *
 * `placeholder:text-slate-400` is exempt: a placeholder is not scanned by the
 * contrast rule and is not the only label of its field.
 */
import fs from 'fs';
import path from 'path';

const SRC = path.join(__dirname, '..', '..');

const FILES = [
  'pages/login.tsx',
  'pages/experiments/index.tsx',
  'pages/feature-flags/index.tsx',
  'components/admin/AdminSidebar.tsx',
  'components/admin/AdminLayout.tsx',
];

describe('grey text contrast', () => {
  it.each(FILES)('%s uses no slate-400 text', (file) => {
    const source = fs.readFileSync(path.join(SRC, file), 'utf8');
    const hits = source.match(/(?<!placeholder:)\btext-slate-400\b/g);
    expect(hits).toBeNull();
  });
});
