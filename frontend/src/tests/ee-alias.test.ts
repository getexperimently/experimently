/**
 * The `@ee/*` alias must mean the same thing in all three toolchains.
 *
 * The failure this guards against is the quiet one: a Community build that
 * keeps resolving `@ee/*` to the real Enterprise module and ships it anyway.
 * So each toolchain is checked for the same two facts —
 *
 *   1. an Enterprise tree resolves `@ee/x` to `src/ee/x`;
 *   2. a Community tree can only reach `src/ee-stub/x`.
 *
 * Fact (2) is proven without deleting anything by `@ee/ce-fallback-probe`, a
 * module that exists **only** in the stub tree: resolving it at all means the
 * fallback leg is live. It stands in for every `@ee/*` import once
 * `scripts/community_build.sh` has removed `src/ee`, which the mirror test at
 * the bottom of this file shows is a complete substitution.
 *
 * webpack cannot be resolved in-process (Next bundles its own copy), so it is
 * covered by the config assertions here plus a real
 * `EXPERIMENTLY_EDITION=ce npx next build`, which renders the stub pages into
 * `out/` — see the seam notes in `next.config.js`.
 */
import fs from 'fs';
import path from 'path';

import { RESOLVED_FROM } from '@ee/ce-fallback-probe';
import { RbacService } from '@ee/rbac';

const FRONTEND_ROOT = path.resolve(__dirname, '..', '..');
const EE_DIR = path.join(FRONTEND_ROOT, 'src', 'ee');
const EE_STUB_DIR = path.join(FRONTEND_ROOT, 'src', 'ee-stub');
const eeAlias = require(path.join(FRONTEND_ROOT, 'ee-alias.js'));

/** `tsc` accepts JSONC; strip whole-line `//` comments before parsing. */
function readJsonc(file: string): Record<string, any> {
  const text = fs.readFileSync(file, 'utf8').replace(/^[ \t]*\/\/.*$/gm, '');
  return JSON.parse(text);
}

/** Every `.ts`/`.tsx` module in a tree, as an extensionless relative path. */
function moduleNames(root: string): string[] {
  if (!fs.existsSync(root)) return [];
  const out: string[] = [];
  const walk = (dir: string) => {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        walk(full);
        continue;
      }
      if (!/\.(ts|tsx)$/.test(entry.name)) continue;
      if (/\.(test|spec)\.tsx?$/.test(entry.name) || entry.name.endsWith('.d.ts')) continue;
      out.push(path.relative(root, full).replace(/\.(ts|tsx)$/, '').split(path.sep).join('/'));
    }
  };
  walk(root);
  return out.sort();
}

const enterpriseTree = eeAlias.enterpriseTreeAvailable();

describe('the @ee/* alias — one rule, three toolchains', () => {
  describe('the rule itself (ee-alias.js)', () => {
    it('is Enterprise when src/ee exists and EXPERIMENTLY_EDITION is not "ce"', () => {
      expect(eeAlias.enterpriseTreeAvailable({})).toBe(fs.existsSync(EE_DIR));
    });

    it('is Community whenever EXPERIMENTLY_EDITION=ce, even with src/ee present', () => {
      expect(eeAlias.enterpriseTreeAvailable({ EXPERIMENTLY_EDITION: 'ce' })).toBe(false);
      expect(eeAlias.eeAliasTargets({ EXPERIMENTLY_EDITION: 'ce' })).toEqual([EE_STUB_DIR]);
    });

    it('is case-insensitive about the edition name', () => {
      expect(eeAlias.enterpriseTreeAvailable({ EXPERIMENTLY_EDITION: 'CE' })).toBe(false);
    });

    it('puts the real tree first and the stub second when Enterprise', () => {
      expect(eeAlias.eeAliasTargets({})).toEqual(
        fs.existsSync(EE_DIR) ? [EE_DIR, EE_STUB_DIR] : [EE_STUB_DIR],
      );
    });
  });

  describe('jest (moduleNameMapper)', () => {
    it('maps @ee/* before @/*, to an ordered list of directories', () => {
      const config = require(path.join(FRONTEND_ROOT, 'jest.config.js'));
      const keys = Object.keys(config.moduleNameMapper);
      expect(keys.indexOf('^@ee/(.*)$')).toBeLessThan(keys.indexOf('^@/(.*)$'));
      expect(config.moduleNameMapper['^@ee/(.*)$']).toEqual(
        enterpriseTree
          ? ['<rootDir>/src/ee/$1', '<rootDir>/src/ee-stub/$1']
          : ['<rootDir>/src/ee-stub/$1'],
      );
    });

    it('falls through to the stub tree for a module the real tree lacks', () => {
      // Importing this at all proves the second leg of the mapper is live.
      expect(RESOLVED_FROM).toBe('ee-stub');
      expect(require.resolve('@ee/ce-fallback-probe')).toBe(
        path.join(EE_STUB_DIR, 'ce-fallback-probe.ts'),
      );
    });

    it('resolves @ee/rbac to the edition this run is configured for', () => {
      expect(require.resolve('@ee/rbac')).toBe(
        path.join(enterpriseTree ? EE_DIR : EE_STUB_DIR, 'rbac.ts'),
      );
    });

    it('gives @ee/rbac the same call surface in both editions', () => {
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
    const ceTsconfig = readJsonc(path.join(FRONTEND_ROOT, 'tsconfig.ce.json'));

    it('the default config tries the real tree then the stub', () => {
      expect(tsconfig.compilerOptions.paths['@ee/*']).toEqual([
        './src/ee/*',
        './src/ee-stub/*',
      ]);
    });

    it('tsconfig.ce.json resolves @ee/* to the stub tree alone', () => {
      expect(ceTsconfig.compilerOptions.paths['@ee/*']).toEqual(['./src/ee-stub/*']);
      expect(ceTsconfig.extends).toBe('./tsconfig.json');
    });

    it('tsconfig.ce.json also drops src/ee from the program', () => {
      expect(ceTsconfig.exclude).toContain('src/ee');
    });

    it('keeps @/* identical in both, so only the seam differs', () => {
      expect(ceTsconfig.compilerOptions.paths['@/*']).toEqual(
        tsconfig.compilerOptions.paths['@/*'],
      );
    });
  });

  describe('next/webpack', () => {
    const nextConfig = require(path.join(FRONTEND_ROOT, 'next.config.js'));

    it('sets resolve.alias["@ee"] to the same ordered directories', () => {
      const config: any = { resolve: { alias: { '@': path.join(FRONTEND_ROOT, 'src') } } };
      const out = nextConfig.webpack(config);
      expect(out.resolve.alias['@ee']).toEqual(eeAlias.eeAliasTargets());
      // The aliases Next already set survive.
      expect(out.resolve.alias['@']).toBe(path.join(FRONTEND_ROOT, 'src'));
    });

    it('works when Next hands it a config with no alias map yet', () => {
      const out = nextConfig.webpack({ resolve: {} });
      expect(out.resolve.alias['@ee']).toEqual(eeAlias.eeAliasTargets());
    });

    it('makes the edition part of the webpack cache key', () => {
      // Found the hard way: with a shared filesystem cache, `next build` after
      // a build of the other edition reused the cached resolution and emitted
      // the other edition's modules with no error at all.
      const ce = nextConfig.webpack({ resolve: {}, cache: { type: 'filesystem', version: 'abc' } });
      expect(ce.cache.version).toBe(`abc|edition=${enterpriseTree ? 'ee' : 'ce'}`);
      expect(ce.cache.type).toBe('filesystem');
    });

    it('leaves a cache-less config alone', () => {
      expect(() => nextConfig.webpack({ resolve: {} })).not.toThrow();
      expect(nextConfig.webpack({ resolve: {}, cache: true }).cache).toBe(true);
    });

    it('points Next at the tsconfig that agrees with the alias', () => {
      // Otherwise Next's own tsconfig-paths resolution could win back the real
      // module in a Community build without anything failing.
      expect(nextConfig.typescript.tsconfigPath).toBe(
        enterpriseTree ? 'tsconfig.json' : 'tsconfig.ce.json',
      );
    });
  });

  describe('the stub tree is a complete substitution', () => {
    it('mirrors every Enterprise module, so nothing dangles once src/ee is deleted', () => {
      const missing = moduleNames(EE_DIR).filter(
        (name) => moduleNames(EE_STUB_DIR).indexOf(name) === -1,
      );
      expect(missing).toEqual([]);
    });

    it('carries a stub for each of the seven Enterprise routes', () => {
      expect(moduleNames(EE_STUB_DIR)).toEqual(
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
      expect(fs.existsSync(path.join(EE_DIR, 'ce-fallback-probe.ts'))).toBe(false);
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

      // `ee-manifest.txt` lists these page files, so `community_build.sh`
      // deletes them outright and the routes disappear. Either all seven are
      // present (any development tree) or none are (a built Community tree) —
      // a partial set means something deleted half a seam.
      const present = routes.filter((file) => fs.existsSync(file));
      expect([0, routes.length]).toContain(present.length);

      for (const file of present) {
        const source = fs.readFileSync(file, 'utf8');
        expect(source).toMatch(/export \{ default \} from '@ee\/pages\/[^']+';/);
        // A re-export and a doc comment, nothing else: no Enterprise code in
        // the Community page tree.
        expect(source.replace(/\/\*[\s\S]*?\*\//g, '').trim().split('\n')).toHaveLength(1);
      }
    });
  });
});
