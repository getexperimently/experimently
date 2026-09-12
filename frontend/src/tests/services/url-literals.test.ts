/**
 * Guard: every `/api/v1/...` URL the dashboard calls must exist on the backend.
 *
 * Scans `src/**` (services, components, pages, hooks, contexts — everything but
 * tests and mocks) for string and template literals starting with `/api/v1/`,
 * expands `${CONST}` prefixes declared as `const X = '/api/v1/...'` in the same
 * file, normalises `${expr}` / `{name}` segments to `{param}` and checks each
 * against the paths (and, when the call names one, the HTTP method) in
 * `src/tests/fixtures/openapi.json`.
 *
 * Regenerate the fixture after changing backend routes:
 *   npm run openapi:dump   (= python -m backend.scripts.dump_openapi from the repo root)
 */
import fs from 'fs';
import path from 'path';

const SRC_ROOT = path.resolve(__dirname, '..', '..');
const FIXTURE = path.join(SRC_ROOT, 'tests', 'fixtures', 'openapi.json');
const EXCLUDED_DIRS = new Set(['tests', '__mocks__', 'node_modules']);
type HttpMethod = 'get' | 'post' | 'put' | 'patch' | 'delete';

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

export function listSourceFiles(root: string): string[] {
  const out: string[] = [];
  const walk = (dir: string) => {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, entry.name);
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
  const rel = path.relative(SRC_ROOT, file);
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

describe('frontend /api/v1 URL literals match the backend OpenAPI spec', () => {
  const doc: OpenApiDocument = JSON.parse(fs.readFileSync(FIXTURE, 'utf8'));
  const files = listSourceFiles(SRC_ROOT);
  const literals = files.flatMap((f) => extractUrlLiterals(f, fs.readFileSync(f, 'utf8')));

  it('loads a populated OpenAPI fixture (run `npm run openapi:dump` to refresh it)', () => {
    expect(Object.keys(doc.paths).length).toBeGreaterThan(100);
    expect(doc.paths['/api/v1/feature-flags/']).toBeDefined();
  });

  it('finds the URL literals the dashboard uses', () => {
    expect(files.length).toBeGreaterThan(20);
    expect(literals.length).toBeGreaterThan(40);
    const paths = new Set(literals.map((l) => l.path));
    expect(paths).toContain('/api/v1/experiments/{param}');
    expect(paths).toContain('/api/v1/feature-flags/{param}/{param}');
    expect(paths).toContain('/api/v1/auth/login');
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
