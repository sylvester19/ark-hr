import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  async rewrites() {
    return [{ source: "/backend/:path*", destination: "http://127.0.0.1:3000/:path*" }];
  },
};

export default nextConfig;
