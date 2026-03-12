import { execSync } from "child_process";
import { defineConfig } from "vite";
import solidPlugin from "vite-plugin-solid";
import { VitePWA } from "vite-plugin-pwa";
import packageJson from "./package.json" with { type: "json" };

const backendUrl = process.env.VITE_BACKEND_URL || "http://localhost:8000";

function resolveVersion(): string {
  try {
    const branch = execSync("git rev-parse --abbrev-ref HEAD", { encoding: "utf-8" }).trim();
    if (branch === "main") return packageJson.version;
    const hash = execSync("git rev-parse --short HEAD", { encoding: "utf-8" }).trim();
    return `${packageJson.version}+git-${hash}`;
  } catch {
    return packageJson.version;
  }
}

export default defineConfig({
  define: {
    __APP_VERSION__: JSON.stringify(resolveVersion()),
  },
  plugins: [
    solidPlugin(),
    VitePWA({
      registerType: "autoUpdate",
      includeAssets: [
        "default-avatar.svg",
        "apple-touch-icon.svg",
      ],
      manifest: false,
      workbox: {
        globPatterns: ["**/*.{js,css,html,svg,woff,woff2}"],
        runtimeCaching: [
          {
            urlPattern: /^\/api\/(?!v1\/streaming|v1\/instance)/,
            handler: "NetworkFirst",
            options: {
              cacheName: "api-cache",
              expiration: {
                maxEntries: 100,
                maxAgeSeconds: 60 * 5,
              },
              networkTimeoutSeconds: 3,
            },
          },
        ],
      },
    }),
  ],
  server: {
    port: 3000,
    allowedHosts: true,
    proxy: {
      "/api": {
        target: backendUrl,
        changeOrigin: true,
      },
      "/.well-known": {
        target: backendUrl,
        changeOrigin: true,
      },
      "/users": {
        target: backendUrl,
        changeOrigin: true,
      },
      "/inbox": {
        target: backendUrl,
        changeOrigin: true,
      },
      "/nodeinfo": {
        target: backendUrl,
        changeOrigin: true,
      },
      "/manifest.webmanifest": {
        target: backendUrl,
        changeOrigin: true,
      },
    },
  },
  build: {
    target: "esnext",
  },
});
