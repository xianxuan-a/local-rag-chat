export function createAbortError(): DOMException {
  return new DOMException('The operation was cancelled.', 'AbortError')
}

export function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === 'AbortError'
}
