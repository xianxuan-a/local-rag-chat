import { createAbortError } from '@/utils/abort'

export { createAbortError, isAbortError } from '@/utils/abort'

export async function delay(milliseconds: number, signal?: AbortSignal): Promise<void> {
  if (signal?.aborted === true) throw createAbortError()

  const configuredScale = Number(import.meta.env.VITE_MOCK_DELAY_SCALE ?? '1')
  const scale = Number.isFinite(configuredScale) ? Math.max(0, configuredScale) : 1
  const duration = Math.max(0, Math.round(milliseconds * scale))

  await new Promise<void>((resolve, reject) => {
    const timeoutId = window.setTimeout(() => {
      signal?.removeEventListener('abort', abort)
      resolve()
    }, duration)

    function abort(): void {
      window.clearTimeout(timeoutId)
      signal?.removeEventListener('abort', abort)
      reject(createAbortError())
    }

    signal?.addEventListener('abort', abort, { once: true })
  })
}
