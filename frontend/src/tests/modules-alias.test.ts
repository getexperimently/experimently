/**
 * The `@modules/*` alias must mean the same thing in all three toolchains.
 *
 * The failure this guards against is the quiet one: a core build that keeps
 * resolving `@modules/*` to the real module and ships it anyway. So each
 * toolchain is checked for the same two facts —
 *
 *   1. a full-profile tree resolves `@modules/x` to `modules/frontend/src/x`;
 *   2. a core tree can only reach `src/modules-stub/x`.
 *
 * The modules tree sits outside `frontend/` because `modules/` is the optional
 * part of the product: `scripts/core_build.sh` deletes it whole to prove the
 * core profile stands on its own.
 *
 * Fact (2) is proven without deleting anything by `@modules/core-fallback-probe`,
 * a module that exists **only** in the stub tree: resolving it at all means
 * the fallback leg is live. It stands in for every `@modules/*` import once
 * `scripts/core_build.sh` has removed `modules/`, which the substitution test
 * at the bottom of this file shows is complete: every `@modules/*` module a
 * core source imports has a stub.
 *
 * webpack cannot be resolved in-process (Next bundles its own copy), so it is
 * covered by the config assertions here plus a real
 * `EXPERIMENTLY_PROFILE=core npx next build`, which renders the stub pages
 * into `out/` — see the seam notes in `next.config.js`.
 */
import fs from 'fs';
import path from 'path';

import { RESOLVED_FROM } from '@modules/core-fallback-probe';
import { RbacService } from '@modules/rbac';

const FRONTEND_ROOT = path.resolve(__dirname, '..', '..');
const REPO_ROOT = path.resolve(FRONTEND_ROOT, '..');
const MODULES_DIR = path.join(REPO_ROOT, 'modules', 'frontend', 'src');
const MODULES_STUB_DIR = path.join(FRONTEND_ROOT, 'src', 'modules-stub');
const modulesAlias = require(path.join(FRONTEND_ROOT, 'modules-alias.js'));

/** `tsc` accepts JSONC; strip whole-line `//` comments before parsing. */
function readJsonc(file: string): Record<string, any> {
  const text = fs.readFileSync(file, 'utf8').replace(/^[ \t]*\/\/.*$/gm, '');
  return JSON.parse(text);
}

/** Every `.ts`/`.tsx` file in a tree. */
function sourceFiles(root: string): string[] {
  if (!fs.existsSync(root)) return [];
  const out: string[] = [];
  const walk = (dir: string) => {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        if (entry.name !== 'node_modules') walk(full);
        continue;
      }
      if (/\.(ts|tsx)$/.test(entry.name) && !entry.name.endsWith('.d.ts')) out.push(full);
    }
  };
  walk(root);
  return out.sort();
}

/** Every module in a tree (tests excluded), as an extensionless relative path. */
function moduleNames(root: string): string[] {
  return sourceFiles(root)
    .filter((file) => !/\.(test|spec)\.tsx?$/.test(file))
    .map((file) => path.relative(root, file).replace(/\.(ts|tsx)$/, '').split(path.sep).join('/'))
    .sort();
}

/**
 * Every `@modules/x` a tree reaches for: static imports, re-exports,
 * `jest.mock`, `require` and `require.resolve`. Returned as `x`, deduplicated.
 */
function moduleImports(root: string): string[] {
  const found = new Set<string>();
  const re = /(?:from\s*|import\s*\(\s*|require(?:\.resolve)?\s*\(\s*|jest\.mock\s*\(\s*)['"]@modules\/([^'"]+)['"]/g;
  for (const file of sourceFiles(root)) {
    const source = fs.readFileSync(file, 'utf8');
    let m: RegExpExecArray | null;
    while ((m = re.exec(source)) !== null) found.add(m[1]);
  }
  return Array.from(found).sort();
}

const modulesTree = modulesAlias.modulesTreeAvailable();

describe('the @modules/* alias — one rule, three toolchains', () => {
  describe('the rule itself (modules-alias.js)', () => {
    it('points at modules/frontend/src beside the package, never inside it', () => {
      expect(modulesAlias.MODULES_DIR).toBe(MODULES_DIR);
      expect(modulesAlias.MODULES_STUB_DIR).toBe(MODULES_STUB_DIR);
      expect(path.relative(FRONTEND_ROOT, modulesAlias.MODULES_DIR).startsWith('..')).toBe(true);
      // The old location, `frontend/src/modules`, must stay gone: the alias
      // is the only way in.
      expect(fs.existsSync(path.join(FRONTEND_ROOT, 'src', 'modules'))).toBe(false);
    });

    it('is full when modules/frontend/src exists and EXPERIMENTLY_PROFILE is not "core"', () => {
      expect(modulesAlias.modulesTreeAvailable({})).toBe(fs.existsSync(MODULES_DIR));
      expect(modulesAlias.modulesTreeAvailable({ EXPERIMENTLY_PROFILE: 'full' })).toBe(
        fs.existsSync(MODULES_DIR),
      );
    });

    it('is core whenever EXPERIMENTLY_PROFILE=core, even with the tree present', () => {
      expect(modulesAlias.modulesTreeAvailable({ EXPERIMENTLY_PROFILE: 'core' })).toBe(false);
      expect(modulesAlias.modulesAliasTargets({ EXPERIMENTLY_PROFILE: 'core' })).toEqual([
        MODULES_STUB_DIR,
      ]);
    });

    it('is case-insensitive about the profile name', () => {
      expect(modulesAlias.modulesTreeAvailable({ EXPERIMENTLY_PROFILE: 'CORE' })).toBe(false);
    });

    it('puts the real tree first and the stub second when full', () => {
      expect(modulesAlias.modulesAliasTargets({})).toEqual(
        fs.existsSync(MODULES_DIR) ? [MODULES_DIR, MODULES_STUB_DIR] : [MODULES_STUB_DIR],
      );
    });
  });

  describe('jest (moduleNameMapper + roots)', () => {
    const config = require(path.join(FRONTEND_ROOT, 'jest.config.js'));

    it('maps @modules/* before @/*, to an ordered list of directories', () => {
      const keys = Object.keys(config.moduleNameMapper);
      expect(keys.indexOf('^@modules/(.*)$')).toBeLessThan(keys.indexOf('^@/(.*)$'));
      expect(config.moduleNameMapper['^@modules/(.*)$']).toEqual(
        modulesTree
          ? [path.join(MODULES_DIR, '$1'), path.join(MODULES_STUB_DIR, '$1')]
          : [path.join(MODULES_STUB_DIR, '$1')],
      );
    });

    it('collects the module tests only in a full run', () => {
      // They live beside the modules they cover, outside this package, so the
      // default root cannot see them; a core run must not look there.
      expect(config.roots).toEqual(modulesTree ? ['<rootDir>', MODULES_DIR] : ['<rootDir>']);
      const ignored = (config.testPathIgnorePatterns as string[]).some((pattern) =>
        new RegExp(pattern).test(path.join(MODULES_DIR, 'rbac.test.ts')),
      );
      expect(ignored).toBe(!modulesTree);
    });

    it('falls through to the stub tree for a module the real tree lacks', () => {
      // Importing this at all proves the second leg of the mapper is live.
      expect(RESOLVED_FROM).toBe('modules-stub');
      expect(require.resolve('@modules/core-fallback-probe')).toBe(
        path.join(MODULES_STUB_DIR, 'core-fallback-probe.ts'),
      );
    });

    it('resolves @modules/rbac to the profile this run is configured for', () => {
      expect(require.resolve('@modules/rbac')).toBe(
        path.join(modulesTree ? MODULES_DIR : MODULES_STUB_DIR, 'rbac.ts'),
      );
    });

    it('gives @modules/rbac the same call surface in both profiles', () => {
      expect(Object.keys(RbacService).sort()).toEqual([
        'createRole',
        'deleteRole',
        'getUserPermissions',
        'listRoles',
        'updateRole',
      ]);
    });
  });

  describe('typescript (tsconfig paths)', () => {
    const tsconfig = readJsonc(path.join(FRONTEND_ROOT, 'tsconfig.json'));
    const coreTsconfig = readJsonc(path.join(FRONTEND_ROOT, 'tsconfig.core.json'));

    it('the default config tries the real tree then the stub', () => {
      expect(tsconfig.compilerOptions.paths['@modules/*']).toEqual([
        '../modules/frontend/src/*',
        './src/modules-stub/*',
      ]);
    });

    it('the default config type-checks the modules tree, tests included', () => {
      // `paths` alone only pulls in what something imports; the module tests
      // import nothing from here, so they have to be in `include`.
      expect(tsconfig.include).toEqual(
        expect.arrayContaining([
          '../modules/frontend/src/**/*.ts',
          '../modules/frontend/src/**/*.tsx',
        ]),
      );
    });

    it('tsconfig.core.json resolves @modules/* to the stub tree alone', () => {
      expect(coreTsconfig.compilerOptions.paths['@modules/*']).toEqual(['./src/modules-stub/*']);
      expect(coreTsconfig.extends).toBe('./tsconfig.json');
    });

    it('tsconfig.core.json also drops the modules tree from the program', () => {
      expect(coreTsconfig.exclude).toContain('../modules');
    });

    it('keeps every other path identical in both, so only the seam differs', () => {
      // `extends` replaces `paths` wholesale, so tsconfig.core.json repeats
      // the list; this is what keeps the two from drifting apart.
      const strip = (paths: Record<string, string[]>) => {
        const { '@modules/*': _seam, ...rest } = paths;
        return rest;
      };
      expect(strip(coreTsconfig.compilerOptions.paths)).toEqual(
        strip(tsconfig.compilerOptions.paths),
      );
    });

    it('routes every package the modules tree imports to this node_modules', () => {
      // The modules tree is outside the package, so the node_modules walk-up
      // from its files finds nothing; tsconfig `paths` carries a deliberately
      // narrow whitelist instead of a `*` catch-all (a catch-all rewires
      // nested-version resolution inside node_modules). A new bare import in
      // modules/frontend/src needs a matching key here.
      if (!fs.existsSync(MODULES_DIR)) return;
      const keys = Object.keys(tsconfig.compilerOptions.paths);
      const covered = (specifier: string) =>
        keys.some((key) =>
          key.endsWith('/*') ? specifier.startsWith(key.slice(0, -1)) : key === specifier,
        );
      const bare = new Set<string>();
      const re = /(?:from\s*|import\s*\(\s*|require\s*\(\s*|jest\.mock\s*\(\s*)['"]([^'"]+)['"]/g;
      for (const file of sourceFiles(MODULES_DIR)) {
        const source = fs.readFileSync(file, 'utf8');
        let m: RegExpExecArray | null;
        while ((m = re.exec(source)) !== null) {
          const spec = m[1];
          if (spec.startsWith('.') || spec.startsWith('@/') || spec.startsWith('@modules/')) continue;
          bare.add(spec);
        }
      }
      expect(Array.from(bare).sort()).toEqual(
        expect.arrayContaining(['react', 'next/link', 'next/router', '@testing-library/react']),
      );
      const uncovered = Array.from(bare).filter((spec) => !covered(spec));
      expect(uncovered).toEqual([]);
      // Every whitelisted target really is under this package's node_modules.
      for (const key of keys) {
        if (key === '@/*' || key === '@modules/*') continue;
        for (const target of tsconfig.compilerOptions.paths[key] as string[]) {
          expect(target.startsWith('./node_modules/')).toBe(true);
        }
      }
    });
  });

  describe('next/webpack', () => {
    const nextConfig = require(path.join(FRONTEND_ROOT, 'next.config.js'));

    it('sets resolve.alias["@modules"] to the same ordered directories', () => {
      const config: any = { resolve: { alias: { '@': path.join(FRONTEND_ROOT, 'src') } } };
      const out = nextConfig.webpack(config);
      expect(out.resolve.alias['@modules']).toEqual(modulesAlias.modulesAliasTargets());
      // The aliases Next already set survive.
      expect(out.resolve.alias['@']).toBe(path.join(FRONTEND_ROOT, 'src'));
    });

    it('works when Next hands it a config with no alias map yet', () => {
      const out = nextConfig.webpack({ resolve: {} });
      expect(out.resolve.alias['@modules']).toEqual(modulesAlias.modulesAliasTargets());
    });

    it('lets webpack compile sources outside the package (the modules tree)', () => {
      // Without `externalDir` Next's SWC loader only accepts files under the
      // project directory, and `@modules/pages/...` resolved to
      // `../modules/...` fails to parse — a build error in the full profile,
      // silence in core.
      expect(nextConfig.experimental.externalDir).toBe(true);
    });

    it('makes the profile part of the webpack cache key', () => {
      // Found the hard way: with a shared filesystem cache, `next build` after
      // a build of the other profile reused the cached resolution and emitted
      // the other profile's modules with no error at all.
      const out = nextConfig.webpack({ resolve: {}, cache: { type: 'filesystem', version: 'abc' } });
      expect(out.cache.version).toBe(`abc|profile=${modulesTree ? 'full' : 'core'}`);
      expect(out.cache.type).toBe('filesystem');
    });

    it('leaves a cache-less config alone', () => {
      expect(() => nextConfig.webpack({ resolve: {} })).not.toThrow();
      expect(nextConfig.webpack({ resolve: {}, cache: true }).cache).toBe(true);
    });

    it('points Next at the tsconfig that agrees with the alias', () => {
      // Otherwise Next's own tsconfig-paths resolution could win back the real
      // module in a core build without anything failing.
      expect(nextConfig.typescript.tsconfigPath).toBe(
        modulesTree ? 'tsconfig.json' : 'tsconfig.core.json',
      );
    });
  });

  describe('the stub tree is a complete substitution', () => {
    const stubs = moduleNames(MODULES_STUB_DIR);

    it('carries a stub for every @modules/* module a core source reaches for', () => {
      // Core sources are everything under frontend/src, tests included: a core
      // test that does `jest.mock('@modules/rbac')` needs the stub as much as
      // a page does. Modules only the modules tree imports (the roles
      // components, the workspace service) leave with it and need none.
      const wanted = moduleImports(path.join(FRONTEND_ROOT, 'src'));
      expect(wanted).toContain('rbac');
      expect(wanted).toContain('pages/admin/roles');
      const missing = wanted.filter((name) => stubs.indexOf(name) === -1);
      expect(missing).toEqual([]);
    });

    it('carries a stub for each of the seven module routes', () => {
      expect(stubs).toEqual(
        expect.arrayContaining([
          'pages/admin/roles',
          'pages/workspaces/index',
          'pages/workspaces/new',
          'pages/workspaces/[id]/index',
          'pages/workspaces/[id]/members',
          'pages/workspaces/[id]/api-keys',
          'pages/workspaces/invites/[token]',
        ]),
      );
    });

    it('never shadows the probe with a real module', () => {
      expect(fs.existsSync(path.join(MODULES_DIR, 'core-fallback-probe.ts'))).toBe(false);
    });

    it('never keeps a stub for a module the modules tree no longer has', () => {
      // The other direction: a stub that outlives its module would be what a
      // full build silently ships. Only checkable while the tree is on disk.
      if (!fs.existsSync(MODULES_DIR)) return;
      const real = moduleNames(MODULES_DIR);
      const orphaned = stubs.filter(
        (name) => name !== 'core-fallback-probe' && real.indexOf(name) === -1,
      );
      expect(orphaned).toEqual([]);
    });

    it('keeps every module page behind a module gate or an admin guard', () => {
      // A bookmarked URL still reaches the page on an instance that does not
      // have the module; `withModule` renders the same notice the core stub
      // does. The one admin route is additionally guarded so the notice is
      // not the one admin page a VIEWER can open.
      if (!fs.existsSync(MODULES_DIR)) return;
      const pages = sourceFiles(path.join(MODULES_DIR, 'pages'));
      expect(pages).toHaveLength(7);
      for (const file of pages) {
        const source = fs.readFileSync(file, 'utf8');
        expect(source).toMatch(/withModule\(/);
      }
      expect(
        fs.readFileSync(path.join(MODULES_DIR, 'pages', 'admin', 'roles.tsx'), 'utf8'),
      ).toMatch(/withAdminGuard\(/);
      expect(
        fs.readFileSync(path.join(MODULES_STUB_DIR, 'pages', 'admin', 'roles.tsx'), 'utf8'),
      ).toMatch(/withAdminGuard\(/);
    });

    it('leaves the seven page files in src/pages as one-line re-exports', () => {
      const routes = [
        'admin/roles.tsx',
        'workspaces/index.tsx',
        'workspaces/new.tsx',
        'workspaces/[id]/index.tsx',
        'workspaces/[id]/members.tsx',
        'workspaces/[id]/api-keys.tsx',
        'workspaces/invites/[token].tsx',
      ].map((route) => path.join(FRONTEND_ROOT, 'src', 'pages', route));

      // These page files are core (not in `modules-manifest.txt`): a core
      // build keeps them, and `@modules/pages/*` resolves them to the stubs.
      // Either all seven are present or none are — a partial set means
      // something deleted half a seam.
      const present = routes.filter((file) => fs.existsSync(file));
      expect([0, routes.length]).toContain(present.length);

      for (const file of present) {
        const source = fs.readFileSync(file, 'utf8');
        expect(source).toMatch(/export \{ default \} from '@modules\/pages\/[^']+';/);
        // A re-export and a doc comment, nothing else: no module code in the
        // core page tree.
        expect(source.replace(/\/\*[\s\S]*?\*\//g, '').trim().split('\n')).toHaveLength(1);
      }
    });

    it('the modules tree imports core code through @/*, never by relative path', () => {
      // `../../frontend/src/...` would work in every toolchain and bypass the
      // seam; `@/*` keeps the direction of the dependency visible.
      if (!fs.existsSync(MODULES_DIR)) return;
      for (const file of sourceFiles(MODULES_DIR)) {
        const source = fs.readFileSync(file, 'utf8');
        expect(source).not.toMatch(/from\s+['"](\.\.\/)+frontend\//);
        expect(source).not.toMatch(/from\s+['"]@\/modules\//);
      }
    });
  });
});

// ---------------------------------------------------------------------------
// The image build is the fourth toolchain
// ---------------------------------------------------------------------------

describe('the dashboard image', () => {
  const DASHBOARD_DOCKERFILE = path.join(FRONTEND_ROOT, 'Dockerfile');
  const API_DOCKERFILE = path.join(REPO_ROOT, 'backend', 'Dockerfile');

  /** The profile a `docker build` with no `--build-arg` gets. */
  function dashboardDefaultProfile(): string {
    const match = /^ARG\s+EXPERIMENTLY_PROFILE=(\S+)\s*$/m.exec(
      fs.readFileSync(DASHBOARD_DOCKERFILE, 'utf8'),
    );
    expect(match).not.toBeNull();
    return match![1];
  }

  /** The stage a `docker build` with no `--target` builds: the last one. */
  function lastStage(file: string): string {
    const names = fs
      .readFileSync(file, 'utf8')
      .split('\n')
      .map((line) => /^FROM\s+\S+\s+AS\s+(\S+)\s*$/i.exec(line))
      .filter((m): m is RegExpExecArray => m !== null)
      .map((m) => m[1]);
    expect(names.length).toBeGreaterThan(0);
    return names[names.length - 1];
  }

  it('defaults to the same profile the API image defaults to', () => {
    // A self-hoster who copies the two documented `docker build` lines must
    // get a matching pair. A full dashboard against a core API is module nav
    // pointed at 404s; and on a core checkout, which has no modules/ at all,
    // a full dashboard build cannot even copy modules/frontend/.
    expect(dashboardDefaultProfile()).toBe('core');
    expect(lastStage(API_DOCKERFILE)).toBe('core');
  });

  it('documents as the default the profile it actually defaults to', () => {
    const labelled = /^#\s+(\w+) \(default\)/m.exec(
      fs.readFileSync(DASHBOARD_DOCKERFILE, 'utf8'),
    );
    expect(labelled).not.toBeNull();
    expect(labelled![1]).toBe(dashboardDefaultProfile());
  });

  it('asserts the built bundle matches the profile, both ways', () => {
    // The build fails itself if the bundle and the profile disagree. Both
    // branches have to carry an assertion or one profile goes unchecked.
    const text = fs.readFileSync(DASHBOARD_DOCKERFILE, 'utf8');
    expect(text).toMatch(/if \[ "\$EXPERIMENTLY_PROFILE" = "core" \]; then/);
    // core: no module route in the bundle, and the stub page is there instead.
    expect(text).toMatch(/! grep -rlE '\/api\/v1\/workspaces\|\/api\/v1\/rbac\/' out\/_next\/static/);
    // full: the modules tree was really copied, and its code really shipped.
    expect(text).toMatch(/test -d \/app\/modules\/frontend\/src/);
    expect(text).toMatch(/&& grep -rlE '\/api\/v1\/rbac\/' out\/_next\/static/);
  });
});
