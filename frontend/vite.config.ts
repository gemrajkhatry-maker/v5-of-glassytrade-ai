import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The TradeX API is CORS-enabled (allow_origins=["*"]), so the dev server
// talks to it cross-origin directly. Point VITE_API_BASE at the backend
// (default http://localhost:8000) when it is not on the same origin.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
  },
});
