import path from 'node:path'

import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vitest/config'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: [
      {
        find: '@/api/adapters/runtimeAdapter',
        replacement: path.resolve(
          import.meta.dirname,
          './src/api/adapters/mockRuntimeAdapter.ts',
        ),
      },
      {
        find: '@',
        replacement: path.resolve(import.meta.dirname, './src'),
      },
    ],
  },
  test: {
    environment: 'jsdom',
    globals: true,
    include: ['src/**/*.spec.ts'],
    restoreMocks: true,
    clearMocks: true,
  },
})
