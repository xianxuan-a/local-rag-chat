import { AppError, type ApiMode } from '@/types'

export interface ApiConfig {
  mode: ApiMode
  baseUrl: string | null
  timeoutMs: number
}

const DEFAULT_TIMEOUT_MS = 15_000

function readText(env: Record<string, unknown>, key: string): string {
  const value = env[key]
  return typeof value === 'string' ? value.trim() : ''
}

export function parseApiConfig(env: Record<string, unknown>): ApiConfig {
  const rawMode = readText(env, 'VITE_API_MODE')
  if (rawMode !== 'mock' && rawMode !== 'real') {
    throw new AppError(
      'API_CONFIG_MODE_INVALID',
      'VITE_API_MODE 必须明确设置为 mock 或 real。',
      null,
      { kind: 'config' },
    )
  }

  const rawTimeout = readText(env, 'VITE_API_TIMEOUT_MS')
  const timeoutMs = rawTimeout ? Number(rawTimeout) : DEFAULT_TIMEOUT_MS
  if (!Number.isInteger(timeoutMs) || timeoutMs < 100 || timeoutMs > 120_000) {
    throw new AppError(
      'API_CONFIG_TIMEOUT_INVALID',
      'VITE_API_TIMEOUT_MS 必须是 100 到 120000 之间的整数。',
      null,
      { kind: 'config' },
    )
  }

  if (rawMode === 'mock') {
    return { mode: rawMode, baseUrl: null, timeoutMs }
  }

  const rawBaseUrl = readText(env, 'VITE_API_BASE_URL')
  if (rawBaseUrl.startsWith('/') && !rawBaseUrl.startsWith('//')) {
    const parsed = new URL(rawBaseUrl, 'https://nexus-rag.local')
    if (parsed.search || parsed.hash) {
      throw new AppError(
        'API_CONFIG_BASE_URL_INVALID',
        'Real 模式 API 相对路径不能包含查询参数或 fragment。',
        null,
        { kind: 'config' },
      )
    }
    return {
      mode: rawMode,
      baseUrl: rawBaseUrl === '/' ? '/' : rawBaseUrl.replace(/\/+$/, ''),
      timeoutMs,
    }
  }
  let parsed: URL
  try {
    parsed = new URL(rawBaseUrl)
  } catch (cause) {
    throw new AppError(
      'API_CONFIG_BASE_URL_INVALID',
      'Real 模式需要合法的 VITE_API_BASE_URL。',
      null,
      { kind: 'config', cause },
    )
  }
  if (
    !rawBaseUrl ||
    !['http:', 'https:'].includes(parsed.protocol) ||
    parsed.username ||
    parsed.password ||
    parsed.search ||
    parsed.hash
  ) {
    throw new AppError(
      'API_CONFIG_BASE_URL_INVALID',
      'Real 模式需要不含凭据、查询和 fragment 的 HTTP(S) 或根相对 VITE_API_BASE_URL。',
      null,
      { kind: 'config' },
    )
  }

  return {
    mode: rawMode,
    baseUrl: rawBaseUrl.replace(/\/+$/, ''),
    timeoutMs,
  }
}
