const path = require('path');

// The React SDK is consumed straight from source (no build step) so changes in
// sdk/react/src show up in the storefront immediately.
const SDK_ENTRY = path.resolve(__dirname, '../../sdk/react/src/index.ts');

/** @type {import('next').NextConfig} */
module.exports = {
  reactStrictMode: true,
  experimental: {
    // Allow importing files that live outside this package directory (../../sdk/react/src).
    externalDir: true,
  },
  webpack: (config) => {
    config.resolve.alias = {
      ...config.resolve.alias,
      '@experimentation-platform/react-sdk': SDK_ENTRY,
      // Force a single React copy. Without this, the SDK source could resolve
      // sdk/react/node_modules/react and hooks would throw "Invalid hook call".
      react: path.resolve(__dirname, 'node_modules/react'),
      'react-dom': path.resolve(__dirname, 'node_modules/react-dom'),
    };
    return config;
  },
};
