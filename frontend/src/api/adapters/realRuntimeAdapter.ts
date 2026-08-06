import { createRealAdapter } from '@/api/adapters/realAdapter'
import type { ApiConfig } from '@/api/config'
import type { AppApi } from '@/api/contracts'

export function createRuntimeAdapter(config: ApiConfig): AppApi {
  return createRealAdapter(config)
}
