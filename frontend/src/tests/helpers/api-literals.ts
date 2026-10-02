/**
 * Shared source scanner and OpenAPI matcher for the dashboard's API guards.
 *
 * Not a test file (jest collects only `*.test.ts(x)`): it holds the extractor
 * and matcher that two guards share, so neither imports the other.
 *
 *   - `services/url-literals.test.ts` — every `/api/v1/...` literal is a path
 *     (and method) the backend serves.
 *   - `services/query-params.test.ts` — every query key the dashboard sends is
 *     a query parameter of the operation it calls.
 *
 * Both read the same files, expand the same `const X = '/api/v1/...'`
 * constants and match paths the same way (`{param}` wildcards, trailing-slash
 * tolerant), so a path one guard resolves the other resolves too.
 */
import fs from 'fs';
import path from 'path';

/** `frontend/src`. */
export const SRC_ROOT = path.resolve(__dirname, '..', '..');
export const REPO_ROOT = path.resolve(SRC_ROOT, '..', '..');
/** The modules' dashboard tree; absent from a core checkout. */
export const MODULES_SRC_ROOT = path.join(REPO_ROOT, 'modules', 'frontend', 'src');
export const FIXTURE = path.join(SRC_ROOT, 'tests', 'fixtures', 'openapi.json');
export const MODULE_PATHS_FIXTURE = path.join(SRC_ROOT, 'tests', 'fixtures', 'openapi.module-paths.json');
const MODULES_MANIFEST = path.join(REPO_ROOT, 'modules-manifest.txt');
const EXCLUDED_DIRS = new Set(['tests', '__mocks__', 'node_modules']);
export type HttpMethod = 'get' | 'post' | 'put' | 'patch' | 'delete';

/** Which profile this run is checking. */
export const PROFILE: 'core' | 'full' =
  String(process.env.EXPERIMENTLY_PROFILE || '').toLowerCase() === 'core' ? 'core' : 'full';

export interface UrlLiteral {
  file: string;
  line: number;
  raw: string;
  path: string;
  method: HttpMethod | null;
}

export interface OpenApiDocument {
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

/**
 * The dashboard sources a profile ships: the core tree alone (minus anything
 * the manifest marks as module code) for `core`, both trees for `full`.
 */
export function profileSourceFiles(profile: 'core' | 'full', modulePrefixes: string[]): string[] {
  return profile === 'core'
    ? listSourceFiles(SRC_ROOT, modulePrefixes)
    : [...listSourceFiles(SRC_ROOT), ...listSourceFiles(MODULES_SRC_ROOT)];
}

/** Drop block comments and whole-line `//` comments (URLs contain `//`, so only line-leading ones). */
export function stripComments(source: string): string {
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

export function lineOf(source: string, index: number): number {
  return source.slice(0, index).split('\n').length;
}

/** `String.prototype.matchAll` without relying on iterator downlevelling (tsconfig targets es5). */
export function allMatches(re: RegExp, source: string): RegExpExecArray[] {
  const out: RegExpExecArray[] = [];
  const global = new RegExp(re.source, re.flags.includes('g') ? re.flags : `${re.flags}g`);
  let m: RegExpExecArray | null;
  while ((m = global.exec(source)) !== null) {
    out.push(m);
    if (m[0].length === 0) global.lastIndex++;
  }
  return out;
}

/** How a file is named in a report: repository-relative for the modules tree, `src`-relative otherwise. */
export function sourceLabel(file: string): string {
  return file.startsWith(MODULES_SRC_ROOT) ? path.relative(REPO_ROOT, file) : path.relative(SRC_ROOT, file);
}

/** `const BASE = '/api/v1/experiments';` declarations in one (comment-stripped) file. */
export function fileConstants(source: string): Map<string, string> {
  const constants = new Map<string, string>();
  const constRe = /\bconst\s+([A-Za-z_$][\w$]*)\s*(?::[^=]+)?=\s*(['"`])(\/api\/v1\/[^'"`]*)\2/g;
  for (const m of allMatches(constRe, source)) constants.set(m[1], m[3]);
  return constants;
}

export function extractUrlLiterals(file: string, rawSource: string): UrlLiteral[] {
  const source = stripComments(rawSource);
  const rel = sourceLabel(file);
  const found: UrlLiteral[] = [];

  // const BASE = '/api/v1/experiments';
  const constants = fileConstants(source);

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
