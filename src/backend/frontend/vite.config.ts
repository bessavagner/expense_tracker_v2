import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { resolve } from "path";

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: resolve(__dirname, "../static/frontend"),
    emptyOutDir: true,
    rollupOptions: {
      input: resolve(__dirname, "src/mount.tsx"),
      output: {
        entryFileNames: "mount.js",
        chunkFileNames: "[name].js",
        assetFileNames: "[name].[ext]",
      },
    },
  },
});
