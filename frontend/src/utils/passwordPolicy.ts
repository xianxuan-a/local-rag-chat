export const PASSWORD_MIN_CHARACTERS = 8
export const PASSWORD_MAX_UTF8_BYTES = 72

export function passwordCharacterLength(value: string): number {
  return [...value].length
}

export function passwordByteLength(value: string): number {
  return new TextEncoder().encode(value).length
}

export function validatePasswordPolicy(value: string): string | null {
  if (!value) return '请输入密码。'
  if (passwordCharacterLength(value) < PASSWORD_MIN_CHARACTERS) {
    return `密码至少需要 ${PASSWORD_MIN_CHARACTERS} 个字符。`
  }
  if (passwordByteLength(value) > PASSWORD_MAX_UTF8_BYTES) {
    return `密码不能超过 ${PASSWORD_MAX_UTF8_BYTES} 个 UTF-8 字节。`
  }
  return null
}
