import { spawn } from 'node:child_process'
import { fileURLToPath } from 'node:url'

const viteCli = fileURLToPath(
  new URL('../node_modules/vite/bin/vite.js', import.meta.url),
)
const child = spawn(process.execPath, [viteCli, 'build', '--mode', 'real'], {
  env: {
    ...process.env,
    VITE_API_MODE: 'real',
    VITE_API_BASE_URL: process.env.VITE_API_BASE_URL || '/',
  },
  stdio: 'inherit',
})

child.once('error', (error) => {
  console.error(error)
  process.exitCode = 1
})
child.once('exit', (code, signal) => {
  if (signal) {
    console.error(`Vite terminated by signal ${signal}.`)
    process.exitCode = 1
    return
  }
  process.exitCode = code ?? 1
})
