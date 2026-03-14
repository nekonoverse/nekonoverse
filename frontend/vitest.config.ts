import path from "path";
import { defineConfig } from "vitest/config";
import solidPlugin from "vite-plugin-solid";

const packagesUi = path.resolve(__dirname, "../packages/ui/src");

export default defineConfig({
  plugins: [solidPlugin()],
  test: {
    environment: "jsdom",
    globals: true,
    include: [
      "src/**/*.test.{ts,tsx}",
      "../packages/ui/src/**/*.test.{ts,tsx}",
    ],
    setupFiles: ["./src/test-setup.ts"],
  },
  resolve: {
    alias: {
      "@nekonoverse/ui": packagesUi,
      // Ensure packages/ui can resolve external deps via frontend's node_modules
      "mfm-js": path.resolve(__dirname, "node_modules/mfm-js"),
      "dompurify": path.resolve(__dirname, "node_modules/dompurify"),
    },
    conditions: ["development", "browser"],
  },
  server: {
    fs: {
      allow: [
        path.resolve(__dirname),
        path.resolve(__dirname, "../packages"),
      ],
    },
  },
});
