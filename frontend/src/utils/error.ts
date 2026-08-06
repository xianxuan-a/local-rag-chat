import { AppError } from '@/types'

export function getErrorMessage(error: unknown): string {
  if (error instanceof AppError) return error.message
  if (error instanceof Error) return error.message
  return '发生未知错误，请稍后重试。'
}

export function getErrorDetail(error: unknown): string | null {
  if (error instanceof AppError) return error.detail
  return null
}

export function isCancellationError(error: unknown): boolean {
  return (
    (error instanceof AppError && error.kind === 'cancelled') ||
    (error instanceof DOMException && error.name === 'AbortError')
  )
}
