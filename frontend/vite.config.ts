import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The API base URL is read at runtime from VITE_API_BASE_URL (see .env.example).
// No dev proxy: talking to the backend cross-origin in development is the same
// thing the app does in production, so CORS problems surface here rather than
// after deployment.
export default defineConfig({
  plugins: [react()],
  server: { port: 5173 },
  build: { outDir: "dist", sourcemap: true },
});
