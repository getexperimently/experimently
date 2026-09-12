/** @type {import('next').NextConfig} */
const { eeAliasTargets, enterpriseTreeAvailable } = require('./ee-alias');

// Open-core seam. `./ee-alias.js` owns the rule; this file applies it to
// webpack. Next also derives aliases from `tsconfig.json`'s `paths` via its
// own resolve plugin — if that kept mapping `@ee/*` at `src/ee/*` it would
// quietly win back the real module in a Community build, the exact silent
// failure to avoid — so a Community build is also pointed at
// `tsconfig.ce.json`, whose `paths` list the stub tree alone.
const enterprise = enterpriseTreeAvailable();

module.exports = {
  reactStrictMode: true,
  output: 'export',
  images: {
    unoptimized: true,
  },
  typescript: {
    tsconfigPath: enterprise ? 'tsconfig.json' : 'tsconfig.ce.json',
  },
  webpack: (config) => {
    config.resolve = config.resolve || {};
    config.resolve.alias = {
      ...(config.resolve.alias || {}),
      // Array alias: webpack tries each directory in order and uses the first
      // that contains the requested module.
      '@ee': eeAliasTargets(),
    };

    // The edition is external state that webpack cannot see, so it must be part
    // of the cache key. Without this, `next build` after a build of the other
    // edition reuses the cached resolution and silently ships the wrong
    // modules — observed: an Enterprise build emitting the 1.1 kB stub pages
    // from a previous Community build. Changing `cache.version` invalidates
    // the filesystem cache, so the two editions can never share entries.
    if (config.cache && typeof config.cache === 'object') {
      const version = config.cache.version ? `${config.cache.version}|` : '';
      config.cache = {
        ...config.cache,
        version: `${version}edition=${enterprise ? 'ee' : 'ce'}`,
      };
    }

    return config;
  },
  // Security headers are applied at the serving layer (nginx/edge/CDN) for
  // static export deployments.
};
