import { apiClient } from '@/api/client'
export const sessionApi = {
  list: (options?: Parameters<typeof apiClient.listSessions>[0]) =>
    apiClient.listSessions(options),
  get: (id: string, knowledgeBaseId: string) =>
    apiClient.getSession(id, knowledgeBaseId),
  create: (knowledgeBaseId: string) => apiClient.createSession(knowledgeBaseId),
  update: (id: string, knowledgeBaseId: string, title: string) =>
    apiClient.updateSession(id, knowledgeBaseId, title),
  remove: (id: string, knowledgeBaseId: string) =>
    apiClient.deleteSession(id, knowledgeBaseId),
  getMessages: (
    sessionId: string,
    knowledgeBaseId: string,
    options?: Parameters<typeof apiClient.getMessages>[2],
  ) => apiClient.getMessages(sessionId, knowledgeBaseId, options),
}
