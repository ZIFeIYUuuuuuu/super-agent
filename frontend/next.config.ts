import type { NextConfig } from "next";

const isGithubPages = process.env.GITHUB_PAGES === "true";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  ...(isGithubPages
    ? {
        output: "export",
        basePath: "/super-agent",
        assetPrefix: "/super-agent/",
        images: {
          unoptimized: true,
        },
      }
    : {}),
};

export default nextConfig;
