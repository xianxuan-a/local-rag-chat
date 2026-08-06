import type { ApiConfig } from '@/api/config'
import type { AppApi } from '@/api/contracts'
import { mockAdapter } from '@/api/adapters/mockAdapter'

export function createRuntimeAdapter(config: ApiConfig): AppApi {
  void config
  return mockAdapter
}
