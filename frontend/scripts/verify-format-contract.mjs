import path from 'node:path'

import { check, format, getFileInfo, resolveConfig } from 'prettier'

const projectRoot = path.resolve(import.meta.dirname, '..')
const ignorePath = path.join(projectRoot, '.prettierignore')

const generatedPaths = [
  'node_modules/prettier/index.js',
  '.vite/deps/generated.js',
  'dist/index.html',
  'dist-real/index.html',
  'dist-mock/index.html',
  'artifacts/ci/frontend-unit.xml',
  'coverage/index.html',
  'playwright-report/index.html',
  'test-results/format-probe.json',
  'package-lock.json',
]

const maintainedPaths = [
  'src/main.ts',
  'e2e/app.spec.ts',
  'vite.config.ts',
  'vitest.config.ts',
  'playwright.config.ts',
  'prettier.config.mjs',
  'package.json',
  'README.md',
]

for (const relativePath of generatedPaths) {
  const info = await getFileInfo(path.join(projectRoot, relativePath), {
    ignorePath,
  })
  if (!info.ignored) {
    throw new Error(`Generated path is not ignored by Prettier: ${relativePath}`)
  }
}

for (const relativePath of maintainedPaths) {
  const info = await getFileInfo(path.join(projectRoot, relativePath), {
    ignorePath,
  })
  if (info.ignored) {
    throw new Error(`Maintained path is over-ignored by Prettier: ${relativePath}`)
  }
}

const probePath = path.join(projectRoot, 'src/format-regression-probe.ts')
const prettierConfig = (await resolveConfig(probePath)) ?? {}
const malformedSource = 'export const formatProbe={enabled:true,tags:["real","ci"]}\n'
const options = { ...prettierConfig, filepath: probePath }

if (await check(malformedSource, options)) {
  throw new Error('Prettier failed to reject the deliberately malformed source probe')
}

const normalizedSource = await format(malformedSource, options)
if (!(await check(normalizedSource, options))) {
  throw new Error('Prettier failed to accept the normalized source probe')
}

console.log(
  `format_contract=PASS ignored=${generatedPaths.length} maintained=${maintainedPaths.length}`,
)
