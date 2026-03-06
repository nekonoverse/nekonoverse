import { defineConfig } from "vite";
import solidPlugin from "vite-plugin-solid";
import { VitePWA } from "vite-plugin-pwa";

export default defineConfig({
  plugins: [
    solidPlugin(),
    VitePWA({
      registerType: "prompt",
      includeAssets: [
        "default-avatar.svg",
        "apple-touch-icon.svg",
      ],
      manifest: {
        name: "Nekonoverse",
        short_name: "Nekonoverse",
        description: "A cozy Fediverse social network",
        theme_color: "#f5e6f0",
        background_color: "#f5e6f0",
        display: "standalone",
        scope: "/",
        start_url: "/",
        icons: [
          {
            src: "pwa-192x192.svg",
            sizes: "192x192",
            type: "image/svg+xml",
          },
          {
            src: "pwa-512x512.svg",
            sizes: "512x512",
            type: "image/svg+xml",
          },
          {
            src: "pwa-512x512.svg",
            sizes: "512x512",
            type: "image/svg+xml",
            purpose: "maskable",
          },
        ],
      },
      workbox: {
        globPatterns: ["**/*.{js,css,html,svg,woff,woff2}"],
        runtimeCaching: [
          {
            urlPattern: /^\/api\//,
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
        target: "http://localhost:8000",
        changeOrigin: true,
      },
      "/.well-known": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
      "/users": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
      "/inbox": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
      "/nodeinfo": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
  build: {
    target: "esnext",
  },
});
