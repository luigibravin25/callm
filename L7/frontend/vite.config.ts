// configurazione di Vite (server di sviluppo e preview) e di Vitest
import { defineConfig } from "vitest/config";

// indirizzo del back-end da configurazione (variabile d'ambiente), mai nel codice di src/
const backend = process.env.BACKEND_URL ?? "http://127.0.0.1:8001";

// proxy sulla stessa origine: il browser chiama /api/..., Vite inoltra al back-end togliendo /api
const proxy = {
  "/api": {
    target: backend,
    changeOrigin: true,
    rewrite: (percorso: string) => percorso.replace(/^\/api/, ""),
  },
};

export default defineConfig({
  // porta 5173 sia per npm run dev sia per npm run preview, con lo stesso proxy
  server: { port: 5173, proxy },
  preview: { port: 5173, proxy },
  // test unitari in un DOM simulato (jsdom)
  test: { environment: "jsdom", include: ["tests/unit/**/*.test.ts"] },
});
