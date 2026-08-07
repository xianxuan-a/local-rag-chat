import { describe, expect, it } from 'vitest'

import { mockAdapter } from '@/api/adapters/mockAdapter'
import { parseApiConfig } from '@/api/config'
import { loadApiAdapter } from '@/api/adapterLoader'
import { AppError } from '@/types'

describe('API configuration and adapter selection', () => {
  it('selects exactly one adapter from explicit configuration', async () => {
    const mock = await loadApiAdapter(parseApiConfig({ VITE_API_MODE: 'mock' }))
    const real = await loadApiAdapter(
      parseApiConfig({
        VITE_API_MODE: 'real',
        VITE_API_BASE_URL: 'http://127.0.0.1:8000',
      }),
    )

    expect(mock).toBe(mockAdapter)
    expect(real).not.toBe(mockAdapter)
  })

  it.each([{}, { VITE_API_MODE: '' }, { VITE_API_MODE: 'invalid' }])(
    'rejects missing or invalid API mode',
    (env) => {
      expect(() => parseApiConfig(env)).toThrowError(AppError)
    },
  )

  it.each([
    { VITE_API_MODE: 'real' },
    { VITE_API_MODE: 'real', VITE_API_BASE_URL: 'not-a-url' },
    { VITE_API_MODE: 'real', VITE_API_BASE_URL: 'file:///tmp/api' },
    { VITE_API_MODE: 'real', VITE_API_BASE_URL: '//untrusted.example' },
    { VITE_API_MODE: 'real', VITE_API_BASE_URL: '/?token=unsafe' },
    { VITE_API_MODE: 'real', VITE_API_BASE_URL: '/#unsafe' },
  ])('rejects an invalid Real API base URL', (env) => {
    expect(() => parseApiConfig(env)).toThrowError(AppError)
  })

  it('accepts and normalizes safe root-relative Real API base URLs', () => {
    expect(
      parseApiConfig({
        VITE_API_MODE: 'real',
        VITE_API_BASE_URL: '/gateway/',
      }),
    ).toMatchObject({ mode: 'real', baseUrl: '/gateway' })
    expect(
      parseApiConfig({
        VITE_API_MODE: 'real',
        VITE_API_BASE_URL: '/',
      }),
    ).toMatchObject({ mode: 'real', baseUrl: '/' })
  })

  it('does not require a reachable base URL in Mock mode', () => {
    expect(
      parseApiConfig({
        VITE_API_MODE: 'mock',
        VITE_API_BASE_URL: 'not-a-url',
      }),
    ).toEqual({ mode: 'mock', baseUrl: null, timeoutMs: 15_000 })
  })
})
