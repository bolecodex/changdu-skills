import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "../src/changdu/web/static",
    emptyOutDir: false
  },
  server: {
    proxy: {
      "/api": "http://127.0.0.1:7860"
    }
  }
});
