export const ACCESS_TOKEN_STORAGE_KEY = 'nexus-rag-access-token'
export const AUTHENTICATION_EXPIRED_EVENT = 'nexus-rag-authentication-expired'

export type AccessTokenProvider = () => string | null

function jwtExpiration(token: string): number | null {
  const payload = token.split('.')[1]
  if (!payload) return null
  try {
    const normalized = payload.replace(/-/gu, '+').replace(/_/gu, '/')
    const padded = normalized.padEnd(Math.ceil(normalized.length / 4) * 4, '=')
    const decoded = JSON.parse(window.atob(padded)) as unknown
    if (typeof decoded !== 'object' || decoded === null || Array.isArray(decoded)) {
      return null
    }
    const expiration = (decoded as Record<string, unknown>).exp
    return typeof expiration === 'number' && Number.isFinite(expiration)
      ? expiration * 1000
      : null
  } catch {
    return null
  }
}

export function isAccessTokenExpired(token: string, now = Date.now()): boolean {
  const expiration = jwtExpiration(token)
  return expiration !== null && expiration <= now
}

export function getRuntimeAccessToken(): string | null {
  if (typeof window === 'undefined') return null
  const token = window.sessionStorage.getItem(ACCESS_TOKEN_STORAGE_KEY)?.trim()
  if (!token) return null
  if (isAccessTokenExpired(token)) {
    window.sessionStorage.removeItem(ACCESS_TOKEN_STORAGE_KEY)
    return null
  }
  return token
}

export function setRuntimeAccessToken(token: string | null): void {
  if (typeof window === 'undefined') return
  const normalized = token?.trim() ?? ''
  if (normalized) {
    window.sessionStorage.setItem(ACCESS_TOKEN_STORAGE_KEY, normalized)
  } else {
    window.sessionStorage.removeItem(ACCESS_TOKEN_STORAGE_KEY)
  }
}

export function notifyAuthenticationExpired(): void {
  if (typeof window === 'undefined') return
  setRuntimeAccessToken(null)
  window.dispatchEvent(new Event(AUTHENTICATION_EXPIRED_EVENT))
}

export function onAuthenticationExpired(listener: () => void): () => void {
  if (typeof window === 'undefined') return () => undefined
  window.addEventListener(AUTHENTICATION_EXPIRED_EVENT, listener)
  return () => window.removeEventListener(AUTHENTICATION_EXPIRED_EVENT, listener)
}
