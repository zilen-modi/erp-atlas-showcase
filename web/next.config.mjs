/** @type {import('next').NextConfig} */
const api = process.env.ATLAS_API ?? "http://127.0.0.1:8765";

const nextConfig = {
  // chat answers stream for minutes; the dev proxy's default 30 s timeout cut them off
  experimental: { proxyTimeout: 25 * 60 * 1000 },
  // Browser calls /api/* on the Next origin; Next forwards them to `atlas serve`.
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${api}/api/:path*` }];
  },
};

export default nextConfig;
