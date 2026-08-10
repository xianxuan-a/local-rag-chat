import { describe, expect, it } from 'vitest'

import {
  passwordByteLength,
  passwordCharacterLength,
  validatePasswordPolicy,
} from '@/utils/passwordPolicy'

describe('password policy', () => {
  it('accepts eight ASCII or Unicode characters', () => {
    expect(validatePasswordPolicy('12345678')).toBeNull()
    expect(validatePasswordPolicy('密码安全测试通过')).toBeNull()
    expect(passwordCharacterLength('密码安全测试通过')).toBe(8)
  })

  it('rejects seven characters and values beyond the bcrypt byte boundary', () => {
    expect(validatePasswordPolicy('1234567')).toBe('密码至少需要 8 个字符。')
    expect(passwordByteLength('密'.repeat(25))).toBe(75)
    expect(validatePasswordPolicy('密'.repeat(25))).toBe(
      '密码不能超过 72 个 UTF-8 字节。',
    )
  })
})
