import { describe, expect, it } from 'vitest'

import { safeInternalRedirect } from '@/router'

describe('safeInternalRedirect', () => {
  it('keeps local application redirects', () => {
    expect(safeInternalRedirect('/files?knowledgeBaseId=kb-1')).toBe(
      '/files?knowledgeBaseId=kb-1',
    )
  })

  it('rejects external, login-loop and invalid redirects', () => {
    expect(safeInternalRedirect('//example.com')).toBe('/dashboard')
    expect(safeInternalRedirect('/\\example.com')).toBe('/dashboard')
    expect(safeInternalRedirect('/login?redirect=/login')).toBe('/dashboard')
    expect(safeInternalRedirect('https://example.com')).toBe('/dashboard')
    expect(safeInternalRedirect(null)).toBe('/dashboard')
  })

  it('preserves local query strings and hashes after URL normalization', () => {
    expect(safeInternalRedirect('/chat?session=s-1#answer')).toBe(
      '/chat?session=s-1#answer',
    )
  })
})
