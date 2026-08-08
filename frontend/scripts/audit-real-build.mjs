import { readFile } from 'node:fs/promises'
import { resolve } from 'node:path'

const outputRoot = resolve('dist-real')
const manifestPath = resolve(outputRoot, '.vite', 'manifest.json')
const manifest = JSON.parse(await readFile(manifestPath, 'utf8'))
const manifestText = JSON.stringify(manifest)
const metadataPath = resolve(outputRoot, 'build-meta.json')
const metadata = JSON.parse(await readFile(metadataPath, 'utf8'))
const artifactPaths = new Set([resolve(outputRoot, 'index.html'), metadataPath])

for (const entry of Object.values(manifest)) {
  for (const relativePath of [
    entry.file,
    ...(entry.css ?? []),
    ...(entry.assets ?? []),
  ]) {
    if (relativePath) artifactPaths.add(resolve(outputRoot, relativePath))
  }
}

const forbiddenMarkers = [
  'MOCK MODE',
  '产品知识中台',
  '/mock/uploads/',
  'mockAdapter',
  'mockRuntimeAdapter',
  'loginModeMock',
  'src/mocks/',
  '/fixtures/',
  'VITE_MOCK_DELAY_SCALE',
  'http://127.0.0.1:8000',
]
const violations = []
let combinedText = ''

if (
  metadata.build_mode !== 'real' ||
  metadata.api_mode !== 'real' ||
  metadata.production_deployable !== true ||
  metadata.output_directory !== 'dist-real'
) {
  violations.push('build-meta.json does not identify a deployable Real build')
}

for (const marker of forbiddenMarkers) {
  if (manifestText.includes(marker)) violations.push(`${manifestPath}: ${marker}`)
}

for (const artifactPath of artifactPaths) {
  if (!/\.(?:css|html|js)$/u.test(artifactPath)) continue
  const content = await readFile(artifactPath, 'utf8')
  combinedText += content
  for (const marker of forbiddenMarkers) {
    if (content.includes(marker)) violations.push(`${artifactPath}: ${marker}`)
  }
}

if (!combinedText.includes('/api/')) {
  violations.push('Real bundle does not contain an /api/ endpoint')
}

if (violations.length > 0) {
  throw new Error(`Real build audit failed:\n${violations.join('\n')}`)
}

console.log(
  `Real build audit passed: BUILD_MODE=${metadata.build_mode} ` +
    `(${artifactPaths.size} manifest artifacts).`,
)
