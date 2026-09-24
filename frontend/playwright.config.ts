import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 15_000,
  use: {
    baseURL: "http://127.0.0.1:4173",
    headless: true,
  },
  webServer: {
    command: "python tests/e2e/fake_target_app.py",
    url: "http://127.0.0.1:4173/health",
    reuseExistingServer: false,
  },
});
