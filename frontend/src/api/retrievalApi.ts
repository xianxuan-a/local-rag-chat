import { apiClient } from '@/api/client'
import type { RequestOptions } from '@/api/contracts'
import type { RetrievalRequest } from '@/types'

export const retrievalApi = {
  execute: (request: RetrievalRequest, options?: RequestOptions) =>
    apiClient.executeRetrieval(request, options),
}
