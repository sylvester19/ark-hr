import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  experimental: {
    // The rewrite to the API clones the body. The default 10 MB cut-off
    // turns a normal multi-file upload into a broken request.
    middlewareClientMaxBodySize: "250mb",
    proxyTimeout: 300_000,
  },
  async rewrites() {
    return [{ source: "/backend/:path*", destination: "http://127.0.0.1:3000/:path*" }];
  },
};

export default nextConfig;
