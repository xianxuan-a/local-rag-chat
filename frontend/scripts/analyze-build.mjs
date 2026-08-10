import { brotliCompressSync, constants, gzipSync } from 'node:zlib'
import { mkdir, readFile, readdir, stat, writeFile } from 'node:fs/promises'
import path from 'node:path'

const argumentsList = process.argv.slice(2)
const modeIndex = argumentsList.indexOf('--mode')
const mode = modeIndex >= 0 ? argumentsList[modeIndex + 1] : 'real'
const enforceBudget = argumentsList.includes('--enforce')

if (mode !== 'real' && mode !== 'mock') {
  throw new Error('--mode must be real or mock')
}

const projectRoot = path.resolve(import.meta.dirname, '..')
const outputRoot = path.join(projectRoot, `dist-${mode}`)
const manifestPath = path.join(outputRoot, '.vite', 'manifest.json')
const manifest = JSON.parse(await readFile(manifestPath, 'utf8'))

async function listFiles(root, prefix = '') {
  const entries = await readdir(path.join(root, prefix), { withFileTypes: true })
  const files = []
  for (const entry of entries) {
    const relativePath = path.posix.join(prefix.replaceAll('\\', '/'), entry.name)
    if (entry.isDirectory()) files.push(...(await listFiles(root, relativePath)))
    else if (entry.isFile()) files.push(relativePath)
  }
  return files.sort()
}

function manifestClosure(entryKey) {
  const files = new Set()
  const visited = new Set()
  const visit = (key) => {
    if (visited.has(key)) return
    visited.add(key)
    const entry = manifest[key]
    if (!entry) throw new Error(`Manifest entry is missing: ${key}`)
    if (entry.file?.endsWith('.js')) files.add(entry.file)
    for (const importedKey of entry.imports ?? []) visit(importedKey)
  }
  visit(entryKey)
  return files
}

function union(...sets) {
  return new Set(sets.flatMap((set) => [...set]))
}

function difference(left, right) {
  return new Set([...left].filter((value) => !right.has(value)))
}

async function compressedStats(relativePaths) {
  const stats = {
    requests: relativePaths.size,
    raw_bytes: 0,
    gzip_bytes: 0,
    brotli_bytes: 0,
  }
  for (const relativePath of relativePaths) {
    const content = await readFile(path.join(outputRoot, relativePath))
    stats.raw_bytes += content.byteLength
    stats.gzip_bytes += gzipSync(content, { level: 9 }).byteLength
    stats.brotli_bytes += brotliCompressSync(content, {
      params: { [constants.BROTLI_PARAM_QUALITY]: 11 },
    }).byteLength
  }
  return stats
}

const outputFiles = await listFiles(outputRoot)
const outputFileSet = new Set(outputFiles)
for (const [key, entry] of Object.entries(manifest)) {
  for (const importedKey of [
    ...(entry.imports ?? []),
    ...(entry.dynamicImports ?? []),
  ]) {
    if (!manifest[importedKey]) {
      throw new Error(`${key} references a missing manifest entry: ${importedKey}`)
    }
  }
  for (const artifact of [entry.file, ...(entry.css ?? []), ...(entry.assets ?? [])]) {
    if (artifact && !outputFileSet.has(artifact)) {
      throw new Error(`${key} references a missing artifact: ${artifact}`)
    }
  }
}

const indexHtml = await readFile(path.join(outputRoot, 'index.html'), 'utf8')
for (const match of indexHtml.matchAll(/(?:src|href)="(\/assets\/[^"?#]+)"/gu)) {
  const relativePath = match[1].slice(1)
  if (!outputFileSet.has(relativePath)) {
    throw new Error(`index.html references a missing artifact: ${relativePath}`)
  }
}

const appEntryKey = 'index.html'
const layoutEntryKey = 'src/layouts/AppLayout.vue'
const dashboardEntryKey = 'src/views/DashboardView.vue'
const chartEntryKey = Object.keys(manifest).find((key) =>
  key.endsWith('/BaseChart.vue'),
)
const appFiles = manifestClosure(appEntryKey)
const layoutFiles = manifestClosure(layoutEntryKey)
const dashboardFiles = manifestClosure(dashboardEntryKey)
const dashboardWarmCache = union(appFiles, layoutFiles)
const dashboardNavigationFiles = difference(dashboardFiles, dashboardWarmCache)
const dashboardEntryFile = new Set([manifest[dashboardEntryKey].file])
const chartFiles = chartEntryKey ? manifestClosure(chartEntryKey) : new Set()
const deferredChartFiles = difference(
  chartFiles,
  union(dashboardWarmCache, dashboardFiles),
)
const allJavaScriptFiles = new Set(
  outputFiles.filter((relativePath) => relativePath.endsWith('.js')),
)

const chunkSizes = await Promise.all(
  [...allJavaScriptFiles].map(async (relativePath) => ({
    file: relativePath,
    bytes: (await stat(path.join(outputRoot, relativePath))).size,
  })),
)
chunkSizes.sort((left, right) => right.bytes - left.bytes)

const report = {
  schema_version: 1,
  mode,
  output_directory: path.basename(outputRoot),
  file_count: outputFiles.length,
  manifest_entries: Object.keys(manifest).length,
  dashboard_chart_entry: chartEntryKey ?? null,
  dashboard_entry: await compressedStats(dashboardEntryFile),
  dashboard_navigation: await compressedStats(dashboardNavigationFiles),
  dashboard_deferred_chart: await compressedStats(deferredChartFiles),
  total_javascript: await compressedStats(allJavaScriptFiles),
  largest_javascript_chunks: chunkSizes.slice(0, 8),
}

const budgetProblems = []
if (report.dashboard_entry.raw_bytes > 80_000) {
  budgetProblems.push(
    `Dashboard entry exceeds 80000 raw bytes: ${report.dashboard_entry.raw_bytes}`,
  )
}
if (report.dashboard_entry.gzip_bytes > 30_000) {
  budgetProblems.push(
    `Dashboard entry exceeds 30000 gzip bytes: ${report.dashboard_entry.gzip_bytes}`,
  )
}
if (
  report.dashboard_chart_entry === null ||
  report.dashboard_deferred_chart.requests === 0
) {
  budgetProblems.push('Dashboard chart code is not deferred behind an async component')
}
if ((report.largest_javascript_chunks[0]?.bytes ?? 0) > 500_000) {
  budgetProblems.push(
    `Largest JavaScript chunk exceeds 500000 raw bytes: ${report.largest_javascript_chunks[0].bytes}`,
  )
}

const reportDirectory = path.join(projectRoot, 'artifacts', 'ci')
await mkdir(reportDirectory, { recursive: true })
const reportPath = path.join(reportDirectory, `bundle-report-${mode}.json`)
await writeFile(reportPath, `${JSON.stringify(report, null, 2)}\n`, 'utf8')

console.log(JSON.stringify(report, null, 2))
if (enforceBudget && budgetProblems.length > 0) {
  throw new Error(`Bundle budget failed:\n${budgetProblems.join('\n')}`)
}
console.log(`bundle_budget=${enforceBudget ? 'PASS' : 'NOT_ENFORCED'} mode=${mode}`)
