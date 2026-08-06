import { describe, expect, it } from 'vitest'

import {
  formatDateTime,
  formatDuration,
  formatFileSize,
  formatNumber,
  formatScore,
  formatTokenCount,
} from '@/utils/format'

describe('format utilities', () => {
  it('formats numbers and file sizes predictably', () => {
    expect(formatNumber(128_532)).toBe('128,532')
    expect(formatFileSize(512)).toBe('512 B')
    expect(formatFileSize(1_536)).toBe('1.5 KB')
    expect(formatFileSize(2 * 1024 ** 2)).toBe('2.0 MB')
  })

  it('formats duration, tokens and scores', () => {
    expect(formatDuration(128)).toBe('128 ms')
    expect(formatDuration(1_840)).toBe('1.84 s')
    expect(formatTokenCount(512)).toBe('512')
    expect(formatTokenCount(1_228)).toBe('1.2k')
    expect(formatScore(0.9142)).toBe('0.914')
  })

  it('formats an ISO timestamp without exposing an invalid date', () => {
    const output = formatDateTime('2026-07-26T10:42:00.000Z')
    expect(output).toMatch(/07\/26/u)
    expect(output).not.toContain('Invalid')
    expect(formatDateTime('not-a-date')).toBe('—')
  })
})
