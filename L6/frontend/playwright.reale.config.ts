// Playwright sullo stack vero (database, agente con LM Studio, back-end, npm run dev già avviati a mano)
import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "tests/reale",
  // una prova alla volta: lavorano sullo stesso back-end (contano le chat create) e su un solo modello
  workers: 1,
  // una risposta vera con revisioni può durare minuti
  timeout: 360_000,
  use: {
    channel: "chrome",
    baseURL: process.env.E2E_URL ?? "http://127.0.0.1:5173",
    screenshot: "on",
  },
});
