import { apiClient } from '@/api/client'
import type { ChatStreamHandlers } from '@/api/contracts'
import type { ChatMessage, ChatRequest, ChatRetryRequest } from '@/types'

export const chatApi = {
  stream: (request: ChatRequest, handlers: ChatStreamHandlers) =>
    apiClient.streamChat(request, handlers),
  retry: (request: ChatRetryRequest, handlers: ChatStreamHandlers) =>
    apiClient.retryChat(request, handlers),
  cancel: (sessionId: string, assistantMessageId: string, knowledgeBaseId: string) =>
    apiClient.cancelChat(sessionId, assistantMessageId, knowledgeBaseId),
  setFeedback: (
    sessionId: string,
    messageId: string,
    knowledgeBaseId: string,
    feedback: ChatMessage['feedback'],
  ) => apiClient.updateMessageFeedback(sessionId, messageId, knowledgeBaseId, feedback),
}
