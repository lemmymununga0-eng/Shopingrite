import { defineConfig } from "@playwright/test";

// Browser tests run against REAL servers: a FastAPI backend (started in e2e/global-setup.js with throw-away
// databases and local demo sign-in) and the Vite dev server below. Run with: npm run test:e2e
export default defineConfig({
  testDir: "./e2e",
  testMatch: /.*\.spec\.js/,
  globalSetup: "./e2e/global-setup.js",
  globalTeardown: "./e2e/global-teardown.js",
  workers: 1,
  fullyParallel: false,
  timeout: 90_000,
  expect: { timeout: 10_000 },
  reporter: [["list"]],
  outputDir: "test-results",
  use: { baseURL: "http://127.0.0.1:5199", trace: "retain-on-failure", screenshot: "only-on-failure" },
  webServer: {
    command: "npx vite --host 127.0.0.1 --port 5199 --strictPort",
    url: "http://127.0.0.1:5199",
    reuseExistingServer: false,
    timeout: 120_000,
    env: { VITE_API_BASE: "http://127.0.0.1:8799", VITE_SUPABASE_URL: "", VITE_SUPABASE_ANON_KEY: "" },
  },
});
