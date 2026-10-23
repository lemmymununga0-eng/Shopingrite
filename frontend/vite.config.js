import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  optimizeDeps: { include: ["recharts", "lucide-react"] },   // pre-bundle so the dev server never reloads the page mid-use
  server: { host: "0.0.0.0", port: 5173 },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/tests/setup.js"],
    css: false,
    testTimeout: 20000,                       // first renders of the lazy-loaded pages are slow on a busy machine
    hookTimeout: 20000,
    include: ["src/**/*.test.{js,jsx}"],      // browser tests in e2e/ run with Playwright, not Vitest
  },
});
