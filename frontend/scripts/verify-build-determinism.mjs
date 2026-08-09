import { spawn } from 'node:child_process'
import { createHash } from 'node:crypto'
import { mkdir, readFile, readdir, writeFile } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const projectRoot = path.resolve(import.meta.dirname, '..')
const viteCli = fileURLToPath(
  new URL('../node_modules/vite/bin/vite.js', import.meta.url),
)

async function runBuild(mode) {
  await new Promise((resolve, reject) => {
    const child = spawn(process.execPath, [viteCli, 'build', '--mode', mode], {
      cwd: projectRoot,
      env: {
        ...process.env,
        VITE_API_MODE: mode,
        VITE_API_BASE_URL: mode === 'real' ? '/' : '',
      },
      stdio: 'inherit',
    })
    child.once('error', reject)
    child.once('exit', (code, signal) => {
      if (signal) reject(new Error(`Vite ${mode} build ended by ${signal}`))
      else if (code !== 0) reject(new Error(`Vite ${mode} build exited ${code}`))
      else resolve()
    })
  })
}

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

async function snapshot(root) {
  const files = await listFiles(root)
  const hashes = {}
  for (const relativePath of files) {
    const content = await readFile(path.join(root, relativePath))
    hashes[relativePath] = createHash('sha256').update(content).digest('hex')
  }
  return hashes
}

function snapshotDigest(snapshotValue) {
  return createHash('sha256').update(JSON.stringify(snapshotValue)).digest('hex')
}

const results = {}
for (const mode of ['real', 'mock']) {
  const outputRoot = path.join(projectRoot, `dist-${mode}`)
  await runBuild(mode)
  const first = await snapshot(outputRoot)
  const staleChunk = path.join(outputRoot, 'assets', 'removed-import-old-hash.js')
  await mkdir(path.dirname(staleChunk), { recursive: true })
  await writeFile(
    staleChunk,
    'throw new Error("stale chunk must be removed")\n',
    'utf8',
  )

  await runBuild(mode)
  const second = await snapshot(outputRoot)
  if ('assets/removed-import-old-hash.js' in second) {
    throw new Error(`${mode} build retained a stale chunk sentinel`)
  }
  if (JSON.stringify(first) !== JSON.stringify(second)) {
    throw new Error(`${mode} consecutive builds produced different files or hashes`)
  }

  const metadata = JSON.parse(
    await readFile(path.join(outputRoot, 'build-meta.json'), 'utf8'),
  )
  if (
    metadata.build_mode !== mode ||
    metadata.api_mode !== mode ||
    metadata.output_directory !== `dist-${mode}` ||
    metadata.production_deployable !== (mode === 'real')
  ) {
    throw new Error(`${mode} build metadata is inconsistent with its output root`)
  }
  results[mode] = {
    file_count: Object.keys(second).length,
    snapshot_sha256: snapshotDigest(second),
    stale_chunk_removed: true,
  }
}

const artifactDirectory = path.join(projectRoot, 'artifacts', 'ci')
await mkdir(artifactDirectory, { recursive: true })
await writeFile(
  path.join(artifactDirectory, 'build-determinism.json'),
  `${JSON.stringify({ schema_version: 1, modes: results }, null, 2)}\n`,
  'utf8',
)
console.log(`build_determinism=PASS ${JSON.stringify(results)}`)
