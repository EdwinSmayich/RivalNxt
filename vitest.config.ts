import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react-swc";
import path from "path";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: [
      { find: "@", replacement: path.resolve(__dirname, "./src") },
      // The UI kit imports packages with their version in the name
      // ("@radix-ui/react-select@2.1.6"); vite.config.mts maps each to the
      // installed package, and the same rule lets tests render those components.
      { find: /^(@[^/@]+\/[^/@]+|[^/@][^/@]*)@\d+\.\d+\.\d+$/, replacement: "$1" },
    ],
  },
  test: {
    environment: "jsdom",
    globals: true,
    include: ["src/**/__tests__/**/*.{test,spec}.{ts,tsx}"],
    setupFiles: ["./vitest.setup.ts"],
    // Exit 0 when no test files match, so the CI job is green before the
    // first test lands and stays meaningful afterwards.
    passWithNoTests: true,
    restoreMocks: true,
    // Timers and RAF are stubbed per-test; keep suites isolated so a leaked
    // interval in one file cannot affect another.
    isolate: true,
  },
});
