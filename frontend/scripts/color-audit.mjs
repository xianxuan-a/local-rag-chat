import { readFile, readdir } from 'node:fs/promises'
import path from 'node:path'

const root = path.resolve(import.meta.dirname, '../src')
const allowedExtensions = new Set(['.css', '.html', '.ts', '.vue'])
const forbiddenWords =
  /\b(?:purple|violet|indigo|blue|cyan|teal|green|emerald|lime|yellow|amber|orange|red|rose|pink|fuchsia|sky)-\d{2,3}\b|dark:|(?:bg|from|via|to)-gradient-/gi
const hexPattern = /#[0-9a-f]{3,8}\b/gi
const rgbPattern = /rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)/gi
const hslPattern = /hsla?\(\s*([+-]?(?:\d*\.)?\d+)[^\d]+([+-]?(?:\d*\.)?\d+)%/gi
const oklchPattern = /oklch\(\s*[+-]?(?:\d*\.)?\d+\s+([+-]?(?:\d*\.)?\d+)/gi
const gradientPattern = /(?:linear|radial|conic)-gradient\(/gi

const failures = []

async function visit(directory) {
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    const absolute = path.join(directory, entry.name)
    if (entry.isDirectory()) {
      await visit(absolute)
      continue
    }
    if (!allowedExtensions.has(path.extname(entry.name))) continue

    const source = await readFile(absolute, 'utf8')
    const relative = path.relative(root, absolute).replaceAll('\\', '/')
    checkPattern(source, forbiddenWords, relative, 'forbidden color utility')
    checkPattern(source, gradientPattern, relative, 'gradient is not permitted')

    for (const match of source.matchAll(hexPattern)) {
      const value = match[0].slice(1)
      const expanded =
        value.length === 3 || value.length === 4
          ? value
              .slice(0, 3)
              .split('')
              .map((part) => part + part)
              .join('')
          : value.slice(0, 6)
      const [r, g, b] = [
        Number.parseInt(expanded.slice(0, 2), 16),
        Number.parseInt(expanded.slice(2, 4), 16),
        Number.parseInt(expanded.slice(4, 6), 16),
      ]
      if (!(r === g && g === b)) {
        addFailure(relative, source, match.index, `${match[0]} is not neutral`)
      }
    }

    for (const match of source.matchAll(rgbPattern)) {
      const channels = match.slice(1, 4).map(Number)
      if (!(channels[0] === channels[1] && channels[1] === channels[2])) {
        addFailure(relative, source, match.index, `${match[0]} is not neutral`)
      }
    }

    for (const match of source.matchAll(hslPattern)) {
      if (Number(match[2]) !== 0) {
        addFailure(relative, source, match.index, `${match[0]} has saturation`)
      }
    }

    for (const match of source.matchAll(oklchPattern)) {
      if (Number(match[1]) !== 0) {
        addFailure(relative, source, match.index, `${match[0]} has chroma`)
      }
    }
  }
}

function checkPattern(source, pattern, file, message) {
  for (const match of source.matchAll(pattern)) {
    addFailure(file, source, match.index, `${message}: ${match[0]}`)
  }
}

function addFailure(file, source, index, message) {
  const line = source.slice(0, index).split('\n').length
  failures.push(`${file}:${line} ${message}`)
}

await visit(root)

if (failures.length > 0) {
  console.error(`Color audit failed with ${failures.length} issue(s):`)
  for (const failure of failures) console.error(`- ${failure}`)
  process.exitCode = 1
} else {
  console.log('Color audit passed: source uses neutral monochrome tokens only.')
}
