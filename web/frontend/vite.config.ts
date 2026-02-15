import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    // During local development, forward /api/* requests to the Python backend
    proxy: {
      "/api": "http://localhost:8000",
    },
  },
});
