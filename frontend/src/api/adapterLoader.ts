import type { RealAdapterDependencies } from '@/api/adapters/realAdapter'
import type { ApiConfig } from '@/api/config'
import type { AppApi } from '@/api/contracts'

/**
 * Test-only explicit loader used to verify both modes without coupling the
 * production bundle to both adapter implementations.
 */
export async function loadApiAdapter(
  config: ApiConfig,
  realDependencies?: RealAdapterDependencies,
): Promise<AppApi> {
  if (config.mode === 'mock') {
    return (await import('@/api/adapters/mockAdapter')).mockAdapter
  }
  const { createRealAdapter } = await import('@/api/adapters/realAdapter')
  return createRealAdapter(config, realDependencies)
}
