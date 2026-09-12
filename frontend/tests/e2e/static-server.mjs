#!/usr/bin/env node
/**
 * Serve the Next.js static export (`frontend/out`) the way nginx serves it in
 * the shipped image, so the browser journeys exercise the artefact the PR gate
 * and the Docker image actually publish — not `next dev`.
 *
 * `output: 'export'` writes one HTML file per page, including the dynamic ones
 * (`out/experiments/[id].html`). A naive static server 404s on
 * `/experiments/<uuid>`; `frontend/nginx.conf` solves that with location blocks
 * generated from `.next/routes-manifest.json` (see scripts/nginx-routes.mjs).
 * This server reads the same manifest and applies the same precedence:
 *
 *   1. the exact file            (`/_next/static/...`)
 *   2. `<path>.html`             (`/login`      -> `login.html`)
 *   3. `<path>/index.html`       (`/`           -> `index.html`)
 *   4. the dynamic route file    (`/results/ab` -> `results/[id].html`)
 *   5. `404.html`, else a bare 404
 *
 * It also proxies /api, /health and /metrics to the backend (--api, default
 * http://localhost:8000), again like the image: the dashboard and the API share
 * one origin, so the browser sends no CORS preflight. That matters beyond
 * fidelity — the backend counts OPTIONS against the strict 10/min limit on
 * /api/v1/auth/login, so a cross-origin run spends its login budget twice as
 * fast.
 *
 * Usage:
 *   node tests/e2e/static-server.mjs [--dir out] [--port 3100] [--host 127.0.0.1]
 *                                    [--api http://localhost:8000]
 *
 * Playwright starts it automatically (see playwright.config.ts) whenever an
 * export exists; nothing else depends on it.
 */

import { createServer, request as httpRequest } from 'node:http';
import { createReadStream, existsSync, readFileSync, statSync } from 'node:fs';
import { dirname, join, normalize, resolve, extname } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const frontendDir = resolve(here, '..', '..');

const args = process.argv.slice(2);
const argValue = (flag, fallback) => {
  const i = args.indexOf(flag);
  return i >= 0 && args[i + 1] ? args[i + 1] : fallback;
};

const rootDir = resolve(argValue('--dir', join(frontendDir, 'out')));
const manifestPath = resolve(
  argValue('--manifest', join(frontendDir, '.next', 'routes-manifest.json')),
);
const port = Number(argValue('--port', process.env.PLAYWRIGHT_PORT ?? '3100'));
const host = argValue('--host', '127.0.0.1');
const apiOrigin = new URL(argValue('--api', process.env.PLAYWRIGHT_API_URL ?? 'http://localhost:8000'));

/** Paths the backend owns; everything else is served from the export. */
const shouldProxy = (pathname) =>
  pathname === '/api' ||
  pathname.startsWith('/api/') ||
  pathname.startsWith('/health') ||
  pathname.startsWith('/metrics');

if (!existsSync(join(rootDir, 'index.html'))) {
  console.error(`static-server: ${rootDir} has no index.html — run \`npm run build\` first.`);
  process.exit(1);
}

/** Dynamic routes, newest-first is irrelevant: Next's manifest is already ordered. */
const dynamicRoutes = (() => {
  if (!existsSync(manifestPath)) {
    console.warn(`static-server: ${manifestPath} not found — dynamic routes will 404.`);
    return [];
  }
  const manifest = JSON.parse(readFileSync(manifestPath, 'utf8'));
  return (manifest.dynamicRoutes ?? [])
    .map((route) => ({ page: route.page, regex: new RegExp(route.regex), file: `${route.page}.html` }))
    .filter((route) => existsSync(join(rootDir, route.file)));
})();

const CONTENT_TYPES = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.mjs': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.gif': 'image/gif',
  '.ico': 'image/x-icon',
  '.webp': 'image/webp',
  '.woff': 'font/woff',
  '.woff2': 'font/woff2',
  '.ttf': 'font/ttf',
  '.txt': 'text/plain; charset=utf-8',
  '.map': 'application/json; charset=utf-8',
};

/** Absolute path inside `rootDir`, or null when the request escapes it. */
function safeJoin(pathname) {
  const clean = normalize(decodeURIComponent(pathname)).replace(/^(\.\.[/\\])+/, '');
  const target = join(rootDir, clean);
  return target.startsWith(rootDir) ? target : null;
}

function isFile(path) {
  try {
    return statSync(path).isFile();
  } catch {
    return false;
  }
}

/** Resolve a URL path to a file on disk using the nginx precedence above. */
function resolveFile(pathname) {
  const direct = safeJoin(pathname);
  if (direct === null) return null;

  if (isFile(direct)) return direct;
  if (isFile(`${direct}.html`)) return `${direct}.html`;
  if (isFile(join(direct, 'index.html'))) return join(direct, 'index.html');

  for (const route of dynamicRoutes) {
    if (route.regex.test(pathname)) return join(rootDir, route.file);
  }
  return null;
}

/**
 * Forward a request to the API origin, streaming both ways.
 *
 * The client's `Host` header is passed through unchanged, exactly as
 * `frontend/nginx.conf` does (`proxy_set_header Host $http_host`). It matters:
 * several API routes only exist with a trailing slash, so `/api/v1/experiments`
 * answers 307 to the absolute URL built from `Host`. Rewriting it to the
 * upstream host would send the browser to another origin, and a cross-origin
 * redirect drops the `Authorization` header — the dashboard would see a 401,
 * clear its token and bounce to /login mid-journey.
 */
function proxy(req, res) {
  const forwarded = {
    ...req.headers,
    'x-forwarded-for': req.socket.remoteAddress ?? '127.0.0.1',
    'x-forwarded-proto': 'http',
  };
  const upstream = httpRequest(
    {
      protocol: apiOrigin.protocol,
      hostname: apiOrigin.hostname,
      port: apiOrigin.port || (apiOrigin.protocol === 'https:' ? 443 : 80),
      method: req.method,
      path: req.url,
      headers: forwarded,
    },
    (upstreamRes) => {
      res.writeHead(upstreamRes.statusCode ?? 502, upstreamRes.headers);
      upstreamRes.pipe(res);
    },
  );
  upstream.on('error', (err) => {
    console.error(`static-server: proxy to ${apiOrigin.origin}${req.url} failed: ${err.message}`);
    if (!res.headersSent) res.writeHead(502, { 'content-type': 'application/json' });
    res.end(JSON.stringify({ detail: `upstream unreachable: ${err.message}` }));
  });
  req.pipe(upstream);
}

const server = createServer((req, res) => {
  const pathname = new URL(req.url ?? '/', `http://${host}:${port}`).pathname;

  if (shouldProxy(pathname)) {
    proxy(req, res);
    return;
  }

  const file = resolveFile(pathname === '/' ? '/index.html' : pathname);

  if (file === null) {
    const notFound = join(rootDir, '404.html');
    res.writeHead(404, { 'content-type': 'text/html; charset=utf-8' });
    res.end(isFile(notFound) ? readFileSync(notFound) : `Not found: ${pathname}`);
    return;
  }

  const type = CONTENT_TYPES[extname(file)] ?? 'application/octet-stream';
  // Immutable hashed assets may be cached; HTML must not be (a redeploy
  // between runs would otherwise serve the previous build).
  const cache = pathname.startsWith('/_next/static/')
    ? 'public, max-age=31536000, immutable'
    : 'no-store';
  res.writeHead(200, { 'content-type': type, 'cache-control': cache });
  createReadStream(file).pipe(res);
});

server.listen(port, host, () => {
  console.log(
    `static-server: serving ${rootDir} on http://${host}:${port} ` +
      `(${dynamicRoutes.length} dynamic route(s), /api -> ${apiOrigin.origin})`,
  );
});

for (const signal of ['SIGINT', 'SIGTERM']) {
  process.on(signal, () => server.close(() => process.exit(0)));
}
