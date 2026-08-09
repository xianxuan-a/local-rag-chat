import path from 'node:path'

import tailwindcss from '@tailwindcss/vite'
import vue from '@vitejs/plugin-vue'
import { defineConfig, loadEnv } from 'vite'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, import.meta.dirname, '')
  const apiMode = process.env.VITE_API_MODE ?? env.VITE_API_MODE
  if (apiMode !== 'mock' && apiMode !== 'real') {
    throw new Error('VITE_API_MODE must be explicitly set to mock or real')
  }
  const outputDirectory = apiMode === 'mock' ? 'dist-mock' : 'dist-real'
  const buildMetadata = {
    schema_version: 1,
    build_mode: apiMode,
    api_mode: apiMode,
    production_deployable: apiMode === 'real',
    output_directory: outputDirectory,
  }
  console.log(`BUILD_MODE=${apiMode} OUTPUT_DIR=${outputDirectory}`)
  const runtimeAdapter = path.resolve(
    import.meta.dirname,
    apiMode === 'mock'
      ? './src/api/adapters/mockRuntimeAdapter.ts'
      : './src/api/adapters/realRuntimeAdapter.ts',
  )
  const loginMode = path.resolve(
    import.meta.dirname,
    apiMode === 'mock' ? './src/api/loginModeMock.ts' : './src/api/loginModeReal.ts',
  )
  return {
    plugins: [
      vue(),
      tailwindcss(),
      {
        name: 'nexus-build-mode-metadata',
        generateBundle() {
          this.emitFile({
            type: 'asset',
            fileName: 'build-meta.json',
            source: `${JSON.stringify(buildMetadata, null, 2)}\n`,
          })
        },
      },
    ],
    build: {
      outDir: outputDirectory,
      emptyOutDir: true,
      manifest: true,
      rolldownOptions: {
        output: {
          codeSplitting: {
            groups: [
              {
                name: 'zrender',
                test: /[\\/]node_modules[\\/]zrender[\\/]/u,
                priority: 40,
              },
              {
                name: 'echarts',
                test: /[\\/]node_modules[\\/]echarts[\\/]/u,
                priority: 30,
              },
            ],
          },
        },
      },
    },
    resolve: {
      alias: [
        {
          find: '@/api/loginMode',
          replacement: loginMode,
        },
        {
          find: '@/api/adapters/runtimeAdapter',
          replacement: runtimeAdapter,
        },
        {
          find: '@',
          replacement: path.resolve(import.meta.dirname, './src'),
        },
      ],
    },
    server: {
      host: '127.0.0.1',
      port: 5173,
      strictPort: true,
    },
    preview: {
      host: '127.0.0.1',
      port: 4173,
      strictPort: true,
    },
  }
})
