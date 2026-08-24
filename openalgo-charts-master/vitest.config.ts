import { fileURLToPath } from 'node:url';
import { defineConfig } from 'vitest/config';

export default defineConfig({
  // Tiers import shared runtime state (the registries) from the package entry
  // rather than a deep path, so each tier bundle references one instance
  // instead of inlining its own copy. See rollup.config.js.
  resolve: {
    alias: {
      'openalgo-charts': fileURLToPath(new URL('./src/index.ts', import.meta.url)),
    },
  },
  test: {
    include: ['tests/**/*.test.ts'],
    environment: 'node',
    globals: false,
  },
});
