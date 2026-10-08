import { defineConfig } from "vite";

// Static output under web/dist, openable from any static host (contract §5.4.10: no server).
export default defineConfig({
  base: "./",
  build: { target: "es2022", sourcemap: true },
});
