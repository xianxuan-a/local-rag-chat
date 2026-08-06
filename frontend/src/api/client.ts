import { createRuntimeAdapter } from '@/api/adapters/runtimeAdapter'
import { parseApiConfig } from '@/api/config'
import type { AppApi } from '@/api/contracts'

export function createLazyApiClient(adapterPromise: Promise<AppApi>): AppApi {
  return {
    getSettings: async (options) => (await adapterPromise).getSettings(options),
    updateSettings: async (input) => (await adapterPromise).updateSettings(input),
    getDashboard: async (options) => (await adapterPromise).getDashboard(options),
    listKnowledgeBases: async (options) =>
      (await adapterPromise).listKnowledgeBases(options),
    getKnowledgeBase: async (id, options) =>
      (await adapterPromise).getKnowledgeBase(id, options),
    createKnowledgeBase: async (input) =>
      (await adapterPromise).createKnowledgeBase(input),
    updateKnowledgeBase: async (id, input) =>
      (await adapterPromise).updateKnowledgeBase(id, input),
    deleteKnowledgeBase: async (id) => (await adapterPromise).deleteKnowledgeBase(id),
    listFiles: async (knowledgeBaseId, options) =>
      (await adapterPromise).listFiles(knowledgeBaseId, options),
    getFile: async (id) => (await adapterPromise).getFile(id),
    addFile: async (knowledgeBaseId, input) =>
      (await adapterPromise).addFile(knowledgeBaseId, input),
    processFile: async (id, handlers) =>
      (await adapterPromise).processFile(id, handlers),
    deleteFile: async (id) => (await adapterPromise).deleteFile(id),
    listSessions: async (options) => (await adapterPromise).listSessions(options),
    getSession: async (id, knowledgeBaseId) =>
      (await adapterPromise).getSession(id, knowledgeBaseId),
    createSession: async (knowledgeBaseId) =>
      (await adapterPromise).createSession(knowledgeBaseId),
    updateSession: async (id, knowledgeBaseId, title) =>
      (await adapterPromise).updateSession(id, knowledgeBaseId, title),
    deleteSession: async (id, knowledgeBaseId) =>
      (await adapterPromise).deleteSession(id, knowledgeBaseId),
    getMessages: async (sessionId, knowledgeBaseId, options) =>
      (await adapterPromise).getMessages(sessionId, knowledgeBaseId, options),
    updateMessageFeedback: async (sessionId, messageId, knowledgeBaseId, feedback) =>
      (await adapterPromise).updateMessageFeedback(
        sessionId,
        messageId,
        knowledgeBaseId,
        feedback,
      ),
    streamChat: async (request, handlers) =>
      (await adapterPromise).streamChat(request, handlers),
    retryChat: async (request, handlers) =>
      (await adapterPromise).retryChat(request, handlers),
    cancelChat: async (sessionId, assistantMessageId, knowledgeBaseId) =>
      (await adapterPromise).cancelChat(sessionId, assistantMessageId, knowledgeBaseId),
    executeRetrieval: async (request, options) =>
      (await adapterPromise).executeRetrieval(request, options),
    listIndexStates: async (knowledgeBaseId, signal) =>
      (await adapterPromise).listIndexStates(knowledgeBaseId, signal),
    submitIndexRebuild: async (knowledgeBaseId) =>
      (await adapterPromise).submitIndexRebuild(knowledgeBaseId),
    getJob: async (id, signal) => (await adapterPromise).getJob(id, signal),
    cancelJob: async (id) => (await adapterPromise).cancelJob(id),
    abortBuilding: async (knowledgeBaseId) =>
      (await adapterPromise).abortBuilding(knowledgeBaseId),
    rollbackKnowledgeBaseIndex: async (knowledgeBaseId) =>
      (await adapterPromise).rollbackKnowledgeBaseIndex(knowledgeBaseId),
    cleanupKnowledgeBaseIndexes: async (knowledgeBaseId, options) =>
      (await adapterPromise).cleanupKnowledgeBaseIndexes(knowledgeBaseId, options),
    listEvaluationDatasets: async () => (await adapterPromise).listEvaluationDatasets(),
    uploadEvaluationDataset: async (input) =>
      (await adapterPromise).uploadEvaluationDataset(input),
    getEvaluationSummary: async () => (await adapterPromise).getEvaluationSummary(),
    listEvaluationRuns: async () => (await adapterPromise).listEvaluationRuns(),
    createEvaluationRun: async (input) =>
      (await adapterPromise).createEvaluationRun(input),
    getEvaluationRun: async (id, signal) =>
      (await adapterPromise).getEvaluationRun(id, signal),
    listEvaluationCases: async (id, options) =>
      (await adapterPromise).listEvaluationCases(id, options),
  }
}

export const apiConfig = parseApiConfig(import.meta.env)
export const apiClient = createLazyApiClient(
  Promise.resolve(createRuntimeAdapter(apiConfig)),
)
