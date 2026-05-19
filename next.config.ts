import type { NextConfig } from "next";

const withBundleAnalyzer = require('@next/bundle-analyzer')({
  enabled: process.env.ANALYZE === 'true',
})

const nextConfig: NextConfig = {
  /* config options here */
  typescript: {
    ignoreBuildErrors: false, // Fail build on TypeScript errors
  },
  // Use React Strict Mode to catch potential issues
  reactStrictMode: true,
  eslint: {
    // Fail build on ESLint errors
    ignoreDuringBuilds: false,
  },
};

export default withBundleAnalyzer(nextConfig);
