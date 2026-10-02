import { defineConfig } from "@playwright/test";

// Assumes the API (uvicorn, :8000) and the Vite dev server (:5173, proxying /api to
// :8000) are already running against a seeded DB -- same servers Phase 6's manual
// browser playthroughs used, not spun up fresh per test run (the API needs a real
// pipeline-seeded DB, which takes minutes; see docs/PROGRESS.md Phase 6/8).
export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  fullyParallel: false,
  workers: 1,
  reporter: "list",
  use: {
    baseURL: "http://127.0.0.1:5173",
    trace: "retain-on-failure",
  },
});
