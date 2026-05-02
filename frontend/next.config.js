/** @type {import('next').NextConfig} */

module.exports = {
  reactStrictMode: true,
  output: 'export',
  images: {
    unoptimized: true,
  },
  // Security headers are applied at the serving layer (nginx/edge/CDN) for
  // static export deployments.
};
