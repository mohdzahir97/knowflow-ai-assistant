import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    // Node, not jsdom. jsdom supplies its own AbortSignal, which is a
    // different realm from the one Node's fetch expects, and RTK Query's
    // fetchBaseQuery passes a signal on every request - so every call fails
    // with "Expected signal to be an instance of AbortSignal". Nothing under
    // test needs a DOM; it needs fetch (native here) and localStorage, which
    // the setup file provides.
    environment: "node",
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.ts", "src/**/*.test.tsx"],
  },
});
