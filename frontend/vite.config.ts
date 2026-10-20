/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Built files are served by Django under /static/app/ (whitenoise), and the
// page itself at /app/ on each business's own address.
//
// Development: open http://gorkhabutchery.localhost:5173/app/ - API calls are
// forwarded to Django on port 8000 with the same host name, so the business
// is found from the address exactly as in production.
export default defineConfig(({ command }) => ({
  base: command === "build" ? "/static/app/" : "/app/",
  plugins: [react()],
  build: { outDir: "dist", emptyOutDir: true, sourcemap: false },
  server: {
    host: true,
    allowedHosts: [".localhost"],
    proxy: Object.fromEntries(
      ["/api", "/account", "/admin", "/static", "/dashboard", "/settings"].map((p) => [p, { target: "http://localhost:8000", changeOrigin: false }]),
    ),
  },
  test: { environment: "jsdom", globals: true },
}));
