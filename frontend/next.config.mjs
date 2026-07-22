/** @type {import('next').NextConfig} */
const nextConfig = {
  /**
   * Output standalone build for smaller Docker images.
   * Copies only the required files and dependencies into `.next/standalone`.
   */
  output: "standalone",

  /**
   * React strict mode catches potential issues during development.
   */
  reactStrictMode: true,

  /**
   * Proxy API calls to the backend during development.
   * In production, configure your reverse proxy (nginx, ALB, etc.) instead.
   */
  async rewrites() {
    const backendUrl = process.env.BACKEND_URL ?? "http://backend:8000";
    return [
      {
        source: "/api/:path*",
        destination: `${backendUrl}/api/:path*`,
      },
    ];
  },

  /**
   * Disable X-Powered-By header for security hardening.
   */
  poweredByHeader: false,
};

export default nextConfig;
