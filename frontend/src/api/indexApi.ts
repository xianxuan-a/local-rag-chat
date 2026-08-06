import { apiClient } from '@/api/client'

export const indexApi = {
  listStates: (knowledgeBaseId?: string, signal?: AbortSignal) =>
    apiClient.listIndexStates(knowledgeBaseId, signal),
  submitRebuild: (knowledgeBaseId: string) =>
    apiClient.submitIndexRebuild(knowledgeBaseId),
  getJob: (id: string, signal?: AbortSignal) => apiClient.getJob(id, signal),
  cancelJob: (id: string) => apiClient.cancelJob(id),
  abortBuilding: (knowledgeBaseId: string) => apiClient.abortBuilding(knowledgeBaseId),
  rollbackKnowledgeBase: (knowledgeBaseId: string) =>
    apiClient.rollbackKnowledgeBaseIndex(knowledgeBaseId),
  cleanupKnowledgeBase: (
    knowledgeBaseId: string,
    cleanupPrevious: boolean,
    cleanupOrphans: boolean,
  ) =>
    apiClient.cleanupKnowledgeBaseIndexes(knowledgeBaseId, {
      cleanupPrevious,
      cleanupOrphans,
    }),
}
