import { execSync } from "child_process";
import path from "path";
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
      strategies: "injectManifest",
      srcDir: "src",
      filename: "sw.ts",
      registerType: "autoUpdate",
      includeAssets: [
        "default-avatar.svg",
        "apple-touch-icon.svg",
      ],
      manifest: false,
      injectManifest: {
        globPatterns: ["**/*.{js,css,html,svg,woff,woff2}"],
      },
    }),
  ],
  server: {
    port: 3000,
    allowedHosts: true,
    fs: {
      allow: [
        path.resolve(__dirname),
        path.resolve(__dirname, "../packages"),
      ],
    },
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
  resolve: {
    alias: {
      "@nekonoverse/ui": path.resolve(__dirname, "../packages/ui/src"),
      "solid-js": path.resolve(__dirname, "node_modules/solid-js"),
      "mfm-js": path.resolve(__dirname, "node_modules/mfm-js"),
      "dompurify": path.resolve(__dirname, "node_modules/dompurify"),
      "@solid-primitives/i18n": path.resolve(__dirname, "node_modules/@solid-primitives/i18n"),
    },
  },
  build: {
    target: "esnext",
  },
});
