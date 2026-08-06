import { apiClient } from '@/api/client'
import type { KnowledgeBaseInput } from '@/types'

export const knowledgeBaseApi = {
  list: () => apiClient.listKnowledgeBases(),
  get: (id: string) => apiClient.getKnowledgeBase(id),
  create: (input: KnowledgeBaseInput) => apiClient.createKnowledgeBase(input),
  update: (id: string, input: KnowledgeBaseInput) =>
    apiClient.updateKnowledgeBase(id, input),
  remove: (id: string) => apiClient.deleteKnowledgeBase(id),
}
