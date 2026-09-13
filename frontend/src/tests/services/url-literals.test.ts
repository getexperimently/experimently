/**
 * Guard: every `/api/v1/...` URL the dashboard calls must exist on the backend.
 *
 * Scans the dashboard sources (services, components, pages, hooks, contexts —
 * everything but tests and mocks) for string and template literals starting
 * with `/api/v1/`, expands `${CONST}` prefixes declared as
 * `const X = '/api/v1/...'` in the same file, normalises `${expr}` / `{name}`
 * segments to `{param}` and checks each against the paths (and, when the call
 * names one, the HTTP method) in `src/tests/fixtures/openapi.json`.
 *
 * Regenerate the fixture after changing backend routes:
 *   npm run openapi:dump   (= python -m backend.scripts.dump_openapi from the repo root)
 *
 * ## Profiles
 *
 * The dump is taken from a full-profile build and carries 62 paths that only
 * the modules serve. A core backend serves the rest, so the rule "every URL
 * literal exists in the dump" needs a profile, not a single document. Rather
 * than keeping two dumps in sync, one dump is kept and
 * `openapi.module-paths.json` names the modules' subset:
 *
 *   EXPERIMENTLY_PROFILE=core  →  those 62 paths are removed from the
 *                                 document, and only the core tree
 *                                 (`frontend/src`, minus anything the manifest
 *                                 still lists there) is scanned.
 *   anything else (default)    →  the whole document, and both trees:
 *                                 `frontend/src` and `modules/frontend/src`.
 *
 * The modules' sources live under `modules/frontend/src`, so a core scan
 * never sees them at all; which paths count as module paths is still read
 * from `modules-manifest.txt`, the same file `scripts/core_build.sh` deletes,
 * so this test and the build cannot disagree about where the boundary is.
 */
import fs from 'fs';
import path from 'path';

const SRC_ROOT = path.resolve(__dirname, '..', '..');
const REPO_ROOT = path.resolve(SRC_ROOT, '..', '..');
/** The modules' dashboard tree; absent from a core checkout. */
const MODULES_SRC_ROOT = path.join(REPO_ROOT, 'modules', 'frontend', 'src');
const FIXTURE = path.join(SRC_ROOT, 'tests', 'fixtures', 'openapi.json');
const MODULE_PATHS_FIXTURE = path.join(SRC_ROOT, 'tests', 'fixtures', 'openapi.module-paths.json');
const MODULES_MANIFEST = path.join(REPO_ROOT, 'modules-manifest.txt');
const EXCLUDED_DIRS = new Set(['tests', '__mocks__', 'node_modules']);
type HttpMethod = 'get' | 'post' | 'put' | 'patch' | 'delete';

/** Which profile this run is checking. */
export const PROFILE: 'core' | 'full' =
  String(process.env.EXPERIMENTLY_PROFILE || '').toLowerCase() === 'core' ? 'core' : 'full';

interface UrlLiteral {
  file: string;
  line: number;
  raw: string;
  path: string;
  method: HttpMethod | null;
}

interface OpenApiDocument {
  paths: Record<string, Record<string, unknown>>;
}

// ---------------------------------------------------------------------------
// Source scanning
// ---------------------------------------------------------------------------

/**
 * Dashboard paths `modules-manifest.txt` marks as module code, repository-relative.
 *
 * `modules/frontend` is always included: it is what the `@modules/*` alias
 * resolves to and `scripts/core_build.sh` removes `modules/` whole. Entries
 * still under `frontend/` are honoured too, so a file the manifest lists there
 * is skipped by a core scan even before it has been moved. A missing manifest
 * (a published core tarball) degrades to `modules/frontend` alone rather than
 * failing.
 */
export function moduleSourcePrefixes(manifestFile: string = MODULES_MANIFEST): string[] {
  const prefixes = ['modules/frontend'];
  let text = '';
  try {
    text = fs.readFileSync(manifestFile, 'utf8');
  } catch {
    return prefixes;
  }
  for (const raw of text.split('\n')) {
    const line = raw.split('#')[0].split('::')[0].trim().replace(/\/+$/, '');
    if (!line.startsWith('frontend/') && !line.startsWith('modules/frontend/')) continue;
    if (line && !isModuleSource(line, prefixes)) prefixes.push(line);
  }
  return prefixes.sort();
}

/** True when `rel` (a repository-relative path) is under one of `prefixes`. */
export function isModuleSource(rel: string, prefixes: string[]): boolean {
  const norm = rel.split(path.sep).join('/');
  return prefixes.some((prefix) => norm === prefix || norm.startsWith(`${prefix}/`));
}

/**
 * Every non-test `.ts`/`.tsx` under `root`, minus anything under
 * `excludePrefixes` (repository-relative). A root that does not exist (the
 * modules tree in a core checkout) lists nothing.
 */
export function listSourceFiles(root: string, excludePrefixes: string[] = []): string[] {
  const out: string[] = [];
  if (!fs.existsSync(root)) return out;
  const walk = (dir: string) => {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, entry.name);
      if (excludePrefixes.length && isModuleSource(path.relative(REPO_ROOT, full), excludePrefixes)) {
        continue;
      }
      if (entry.isDirectory()) {
        if (!EXCLUDED_DIRS.has(entry.name)) walk(full);
        continue;
      }
      if (!/\.(ts|tsx)$/.test(entry.name)) continue;
      if (/\.(test|spec)\.tsx?$/.test(entry.name) || entry.name.endsWith('.d.ts')) continue;
      out.push(full);
    }
  };
  walk(root);
  return out.sort();
}

/** Drop block comments and whole-line `//` comments (URLs contain `//`, so only line-leading ones). */
function stripComments(source: string): string {
  return source
    .replace(/\/\*[\s\S]*?\*\//g, (m) => m.replace(/[^\n]/g, ' '))
    .replace(/^[ \t]*\/\/.*$/gm, (m) => ' '.repeat(m.length));
}

/** `${anything}` and `{name}` become `{param}`; a query string is dropped. */
export function normalisePath(raw: string): string {
  return raw
    .replace(/\$\{[^}]*\}/g, '{param}')
    .replace(/\{[^}]*\}/g, '{param}')
    .split('?')[0];
}

/** Find `method: 'POST'` in the call that follows the literal, if it names one. */
function detectMethod(source: string, from: number): HttpMethod | null {
  let window = source.slice(from, from + 600);
  const nextCall = window.search(/\b(?:apiFetch|fetch)\s*(?:<[^>]*>)?\s*\(/);
  if (nextCall > 0) window = window.slice(0, nextCall);
  const m = window.match(/\bmethod\s*:\s*['"](GET|POST|PUT|PATCH|DELETE)['"]/);
  return m ? (m[1].toLowerCase() as HttpMethod) : null;
}

function lineOf(source: string, index: number): number {
  return source.slice(0, index).split('\n').length;
}

/** `String.prototype.matchAll` without relying on iterator downlevelling (tsconfig targets es5). */
function allMatches(re: RegExp, source: string): RegExpExecArray[] {
  const out: RegExpExecArray[] = [];
  const global = new RegExp(re.source, re.flags.includes('g') ? re.flags : `${re.flags}g`);
  let m: RegExpExecArray | null;
  while ((m = global.exec(source)) !== null) {
    out.push(m);
    if (m[0].length === 0) global.lastIndex++;
  }
  return out;
}

export function extractUrlLiterals(file: string, rawSource: string): UrlLiteral[] {
  const source = stripComments(rawSource);
  const rel = file.startsWith(MODULES_SRC_ROOT)
    ? path.relative(REPO_ROOT, file)
    : path.relative(SRC_ROOT, file);
  const found: UrlLiteral[] = [];

  // const BASE = '/api/v1/experiments';
  const constants = new Map<string, string>();
  const constRe = /\bconst\s+([A-Za-z_$][\w$]*)\s*(?::[^=]+)?=\s*(['"`])(\/api\/v1\/[^'"`]*)\2/g;
  for (const m of allMatches(constRe, source)) constants.set(m[1], m[3]);

  // `span` is the length of the matched source text (differs from `raw` once a
  // constant has been expanded); method detection starts right after it.
  const push = (index: number, span: number, raw: string) => {
    found.push({
      file: rel,
      line: lineOf(source, index),
      raw,
      path: normalisePath(raw),
      method: detectMethod(source, index + span),
    });
  };

  // '/api/v1/...' and "/api/v1/..."
  for (const m of allMatches(/(['"])(\/api\/v1\/[^'"\n]*)\1/g, source)) push(m.index, m[0].length, m[2]);

  // `/api/v1/...${x}` and `${BASE}/...`
  for (const m of allMatches(/`([^`]*)`/g, source)) {
    const body = m[1];
    if (body.startsWith('/api/v1/')) {
      push(m.index, m[0].length, body);
      continue;
    }
    const prefix = body.match(/^\$\{([A-Za-z_$][\w$]*)\}/);
    if (prefix && constants.has(prefix[1])) {
      push(m.index, m[0].length, constants.get(prefix[1]) + body.slice(prefix[0].length));
    }
  }

  // apiFetch(BASE, { method: 'POST' }) — a bare constant as the first argument
  for (const m of allMatches(/\bapiFetch\s*(?:<[^>]*>)?\s*\(\s*([A-Za-z_$][\w$]*)\s*[,)]/g, source)) {
    const literal = constants.get(m[1]);
    if (literal) push(m.index, m[0].length, literal);
  }

  return found;
}

// ---------------------------------------------------------------------------
// Per-profile document
// ---------------------------------------------------------------------------

/** The dump with the module paths removed — what a core backend serves. */
export function coreDocument(doc: OpenApiDocument, modulePaths: string[]): OpenApiDocument {
  const paths: OpenApiDocument['paths'] = {};
  const modules = new Set(modulePaths);
  for (const [p, ops] of Object.entries(doc.paths)) {
    if (!modules.has(p)) paths[p] = ops;
  }
  return { paths };
}

// ---------------------------------------------------------------------------
// OpenAPI matching
// ---------------------------------------------------------------------------

function segments(p: string): string[] {
  return p.replace(/\/+$/, '').split('/');
}

function segmentMatches(openapiSeg: string, frontendSeg: string): boolean {
  if (openapiSeg.startsWith('{') && openapiSeg.endsWith('}')) return true;
  if (frontendSeg === '{param}') return true;
  return openapiSeg === frontendSeg;
}

/** OpenAPI paths that a frontend path resolves to (trailing slash tolerant, `{param}` wildcards). */
export function matchingPaths(doc: OpenApiDocument, frontendPath: string): string[] {
  const want = segments(frontendPath);
  return Object.keys(doc.paths).filter((candidate) => {
    const have = segments(candidate);
    return have.length === want.length && have.every((seg, i) => segmentMatches(seg, want[i]));
  });
}

export function findMismatches(doc: OpenApiDocument, literals: UrlLiteral[]): string[] {
  const problems: string[] = [];
  for (const lit of literals) {
    const matches = matchingPaths(doc, lit.path);
    const where = `${lit.file}:${lit.line}`;
    if (matches.length === 0) {
      problems.push(`${where}  ${lit.raw}  →  no backend route matches ${lit.path}`);
      continue;
    }
    if (lit.method && !matches.some((p) => lit.method! in doc.paths[p])) {
      const allowed = matches.map((p) => `${p} [${Object.keys(doc.paths[p]).join(', ')}]`).join('; ');
      problems.push(`${where}  ${lit.method.toUpperCase()} ${lit.raw}  →  method not on ${allowed}`);
    }
  }
  return problems;
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe(`frontend /api/v1 URL literals match the backend OpenAPI spec (${PROFILE})`, () => {
  const fullDoc: OpenApiDocument = JSON.parse(fs.readFileSync(FIXTURE, 'utf8'));
  const modulePaths: string[] = JSON.parse(fs.readFileSync(MODULE_PATHS_FIXTURE, 'utf8')).paths;
  const modulePrefixes = moduleSourcePrefixes();

  const doc = PROFILE === 'core' ? coreDocument(fullDoc, modulePaths) : fullDoc;
  const files =
    PROFILE === 'core'
      ? listSourceFiles(SRC_ROOT, modulePrefixes)
      : [...listSourceFiles(SRC_ROOT), ...listSourceFiles(MODULES_SRC_ROOT)];
  const literals = files.flatMap((f) => extractUrlLiterals(f, fs.readFileSync(f, 'utf8')));

  it('loads a populated OpenAPI fixture (run `npm run openapi:dump` to refresh it)', () => {
    expect(Object.keys(doc.paths).length).toBeGreaterThan(100);
    expect(doc.paths['/api/v1/feature-flags/']).toBeDefined();
    expect(doc.paths['/api/v1/modules']).toBeDefined();
  });

  describe('per-profile fixture', () => {
    it('every path listed as a module path is really in the dump', () => {
      const unknown = modulePaths.filter((p) => !(p in fullDoc.paths));
      expect(unknown).toEqual([]);
    });

    it('the module subset is the 62 paths the modules registration mounts', () => {
      expect(modulePaths).toHaveLength(62);
      expect(modulePaths).toContain('/api/v1/rbac/roles');
      expect(modulePaths).toContain('/api/v1/workspaces/');
      // Routes whose URL is declared on a core router in every profile (501
      // without the module body) are core paths: a core source may name them,
      // so they must not be stripped from the core document.
      expect(modulePaths).not.toContain('/api/v1/compliance/audit-events');
      expect(modulePaths).not.toContain('/api/v1/compliance/export');
      expect(modulePaths).not.toContain('/api/v1/compliance/reports/{standard}');
      expect(modulePaths).not.toContain('/api/v1/experiments/{experiment_id}/split-url/preview');
      // The profile endpoint itself is core: a core build answers it.
      expect(modulePaths).not.toContain('/api/v1/modules');
    });

    it('the core document is the dump minus exactly those paths', () => {
      const core = coreDocument(fullDoc, modulePaths);
      expect(Object.keys(core.paths)).toHaveLength(Object.keys(fullDoc.paths).length - 62);
      expect(core.paths['/api/v1/rbac/roles']).toBeUndefined();
      expect(core.paths['/api/v1/experiments/']).toBeDefined();
      expect(core.paths['/api/v1/modules']).toBeDefined();
    });

    it('a core document rejects a module URL literal, a full one accepts it', () => {
      const literal = {
        file: 'services/admin.ts',
        line: 125,
        raw: '/api/v1/rbac/roles',
        path: '/api/v1/rbac/roles',
        method: null,
      };
      expect(findMismatches(fullDoc, [literal])).toEqual([]);
      const problems = findMismatches(coreDocument(fullDoc, modulePaths), [literal]);
      expect(problems).toHaveLength(1);
      expect(problems[0]).toContain('no backend route');
    });

    it('reads the modules\' dashboard paths out of modules-manifest.txt', () => {
      // The whole modules tree is one manifest entry; the per-module entries
      // inside it (the workspaces and rbac groups) collapse into that prefix.
      expect(modulePrefixes).toEqual(['modules/frontend']);
      expect(isModuleSource('modules/frontend/src/rbac.ts', modulePrefixes)).toBe(true);
      expect(
        isModuleSource('modules/frontend/src/components/admin/roles/RoleTable.tsx', modulePrefixes),
      ).toBe(true);
      expect(isModuleSource('frontend/src/services/admin.ts', modulePrefixes)).toBe(false);
      // The thin re-export pages are core: with modules/frontend gone they
      // resolve to the stub tree and render the "module not installed"
      // notice, which is the designed core experience for those URLs, not a
      // 404.
      expect(isModuleSource('frontend/src/pages/workspaces/index.tsx', modulePrefixes)).toBe(false);
      expect(isModuleSource('frontend/src/pages/admin/roles.tsx', modulePrefixes)).toBe(false);
      // The stub tree is what a core build ships; it must never be listed.
      expect(isModuleSource('frontend/src/modules-stub/rbac.ts', modulePrefixes)).toBe(false);
      // A prefix must not match a sibling that merely starts with the same text.
      expect(isModuleSource('modules/frontend-other/x.ts', modulePrefixes)).toBe(false);
    });

    it('still honours a manifest entry that has not left frontend/ yet', () => {
      const tmp = path.join(SRC_ROOT, 'tests', 'fixtures', 'manifest.tmp-url-literals.txt');
      fs.writeFileSync(
        tmp,
        [
          '# comment',
          'backend/app/x.py',
          'frontend/src/services/legacy.ts   # inline comment',
          'modules/frontend/src/services/workspaces.ts',
          'frontend/src/components/legacy/',
          '',
        ].join('\n'),
      );
      try {
        const prefixes = moduleSourcePrefixes(tmp);
        expect(prefixes).toEqual([
          'frontend/src/components/legacy',
          'frontend/src/services/legacy.ts',
          'modules/frontend',
        ]);
        expect(isModuleSource('frontend/src/services/legacy.ts', prefixes)).toBe(true);
        expect(isModuleSource('frontend/src/services/legacy.tsx', prefixes)).toBe(false);
        expect(isModuleSource('frontend/src/components/legacy/Table.tsx', prefixes)).toBe(true);
      } finally {
        fs.unlinkSync(tmp);
      }
      expect(moduleSourcePrefixes(path.join(SRC_ROOT, 'no-such-manifest.txt'))).toEqual([
        'modules/frontend',
      ]);
    });

    it('never lists the stub tree, which is what a core build ships', () => {
      expect(isModuleSource('frontend/src/modules-stub', modulePrefixes)).toBe(false);
    });
  });

  it('finds the URL literals the dashboard uses', () => {
    expect(files.length).toBeGreaterThan(20);
    expect(literals.length).toBeGreaterThan(40);
    const paths = new Set(literals.map((l) => l.path));
    expect(paths).toContain('/api/v1/experiments/{param}');
    expect(paths).toContain('/api/v1/feature-flags/{param}/{param}');
    expect(paths).toContain('/api/v1/auth/login');
  });

  it(`scans the modules tree only in a full run (${PROFILE})`, () => {
    const moduleFiles = files.filter((f) => f.startsWith(MODULES_SRC_ROOT));
    const paths = new Set(literals.map((l) => l.path));
    if (PROFILE === 'core') {
      // A core scan is the core tree alone, and nothing in it names a module
      // route: that is the whole point of the seam.
      expect(moduleFiles).toEqual([]);
      const moduleLiterals = Array.from(paths).filter(
        (p) => p.startsWith('/api/v1/rbac/') || p.startsWith('/api/v1/workspaces'),
      );
      expect(moduleLiterals).toEqual([]);
    } else if (fs.existsSync(MODULES_SRC_ROOT)) {
      // A full scan checks the modules' sources too, so a URL typo in
      // modules/frontend/src is caught by the same rule as one in frontend/src.
      expect(moduleFiles.length).toBeGreaterThanOrEqual(12);
      expect(paths).toContain('/api/v1/rbac/roles');
      expect(paths).toContain('/api/v1/workspaces/');
      expect(paths).toContain('/api/v1/workspaces/{param}/api-keys/{param}/rotate');
      const moduleTreeLiterals = literals.filter((l) => l.file.startsWith('modules/frontend/src/'));
      expect(moduleTreeLiterals.length).toBeGreaterThanOrEqual(20);
    }
  });

  it('every literal resolves to a backend route with the method it uses', () => {
    const problems = findMismatches(doc, literals);
    expect(problems).toEqual([]);
  });

  describe('extractor', () => {
    const sample = `
      // GET '/api/v1/should-be-ignored'
      /* '/api/v1/also-ignored' */
      const BASE = '/api/v1/things';
      apiFetch<T>(BASE, { query: { a: 1 } });
      apiFetch<T>(BASE, { method: 'POST', json: data });
      apiFetch<T>(\`\${BASE}/\${id}/archive\`, { method: 'POST' });
      apiFetch<T>(\`/api/v1/other/\${encodeURIComponent(key)}?user_id=\${u}\`);
      apiFetch<T>("/api/v1/quoted/{name}", { method: 'DELETE' });
    `;

    it('expands constants, normalises params and detects methods', () => {
      const got = extractUrlLiterals(path.join(SRC_ROOT, 'x.ts'), sample).map((l) => [l.path, l.method]);
      expect(got).toEqual(
        expect.arrayContaining([
          ['/api/v1/things', null],
          ['/api/v1/things', null],
          ['/api/v1/things', 'post'],
          ['/api/v1/things/{param}/archive', 'post'],
          ['/api/v1/other/{param}', null],
          ['/api/v1/quoted/{param}', 'delete'],
        ]),
      );
      expect(got.some(([p]) => String(p).includes('ignored'))).toBe(false);
    });

    it('matches with trailing-slash tolerance and {param} wildcards', () => {
      const mini: OpenApiDocument = {
        paths: {
          '/api/v1/things/': { get: {}, post: {} },
          '/api/v1/things/{thing_id}': { get: {}, put: {} },
          '/api/v1/things/{thing_id}/archive': { post: {} },
        },
      };
      expect(matchingPaths(mini, '/api/v1/things')).toEqual(['/api/v1/things/']);
      expect(matchingPaths(mini, '/api/v1/things/{param}')).toEqual(['/api/v1/things/{thing_id}']);
      expect(matchingPaths(mini, '/api/v1/things/abc/archive')).toEqual(['/api/v1/things/{thing_id}/archive']);
      expect(matchingPaths(mini, '/api/v1/nothing')).toEqual([]);

      const problems = findMismatches(mini, [
        { file: 'a.ts', line: 1, raw: '/api/v1/things/{param}', path: '/api/v1/things/{param}', method: 'delete' },
        { file: 'a.ts', line: 2, raw: '/api/v1/missing', path: '/api/v1/missing', method: null },
        { file: 'a.ts', line: 3, raw: '/api/v1/things', path: '/api/v1/things', method: 'post' },
      ]);
      expect(problems).toHaveLength(2);
      expect(problems[0]).toContain('DELETE');
      expect(problems[1]).toContain('no backend route');
    });
  });
});
