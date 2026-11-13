// Playwright nel browser vero (Chrome installato) con il back-end simulato da page.route
import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "tests/browser",
  // Chrome già installato sul computer: niente download di Chromium
  use: { channel: "chrome", baseURL: "http://127.0.0.1:5174" },
  // server di Vite vero su una porta dedicata; il proxy punta a una porta chiusa:
  // ogni chiamata non simulata fallisce in modo evidente
  webServer: {
    command: "npm run dev -- --port 5174 --strictPort --host 127.0.0.1",
    url: "http://127.0.0.1:5174",
    reuseExistingServer: false,
    env: { BACKEND_URL: "http://127.0.0.1:9" },
  },
});
