import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  ACCESS_TOKEN_STORAGE_KEY,
  getRuntimeAccessToken,
  isAccessTokenExpired,
  notifyAuthenticationExpired,
  onAuthenticationExpired,
  setRuntimeAccessToken,
} from '@/api/auth'

function tokenWithExpiration(expiration: number): string {
  const payload = window
    .btoa(JSON.stringify({ exp: expiration }))
    .replace(/=/gu, '')
    .replace(/\+/gu, '-')
    .replace(/\//gu, '_')
  return `header.${payload}.signature`
}

afterEach(() => {
  window.sessionStorage.clear()
  vi.restoreAllMocks()
})

describe('runtime authentication token', () => {
  it('stores the token only in sessionStorage', () => {
    setRuntimeAccessToken(' short-lived-token ')

    expect(getRuntimeAccessToken()).toBe('short-lived-token')
    expect(window.sessionStorage.getItem(ACCESS_TOKEN_STORAGE_KEY)).toBe(
      'short-lived-token',
    )
    expect(window.localStorage.getItem(ACCESS_TOKEN_STORAGE_KEY)).toBeNull()
  })

  it('removes JWTs after their exp timestamp', () => {
    const expired = tokenWithExpiration(1_700_000_000)
    window.sessionStorage.setItem(ACCESS_TOKEN_STORAGE_KEY, expired)

    expect(isAccessTokenExpired(expired, 1_700_000_001_000)).toBe(true)
    expect(getRuntimeAccessToken()).toBeNull()
    expect(window.sessionStorage.getItem(ACCESS_TOKEN_STORAGE_KEY)).toBeNull()
  })

  it('clears the token and emits one authentication-expired event', () => {
    const listener = vi.fn()
    const unsubscribe = onAuthenticationExpired(listener)
    setRuntimeAccessToken('temporary-token')

    notifyAuthenticationExpired()

    expect(listener).toHaveBeenCalledOnce()
    expect(getRuntimeAccessToken()).toBeNull()
    unsubscribe()
  })
})
