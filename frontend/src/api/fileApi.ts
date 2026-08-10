import { apiClient } from '@/api/client'
import type { ProgressHandlers, RequestOptions } from '@/api/contracts'
import type { FileUploadInput } from '@/types'

export const fileApi = {
  list: (
    knowledgeBaseId: string,
    options?: RequestOptions & { limit?: number; offset?: number },
  ) => apiClient.listFilesPage(knowledgeBaseId, options),
  get: (id: string) => apiClient.getFile(id),
  add: (knowledgeBaseId: string, input: FileUploadInput) =>
    apiClient.addFile(knowledgeBaseId, input),
  process: (id: string, handlers: ProgressHandlers) =>
    apiClient.processFile(id, handlers),
  remove: (id: string) => apiClient.deleteFile(id),
}
