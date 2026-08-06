import { getRuntimeAccessToken } from '@/api/auth'
import type { ApiConfig } from '@/api/config'
import type { AppApi } from '@/api/contracts'
import { HttpClient } from '@/api/http'
import {
  mapFileDto,
  mapEvaluationCaseDto,
  mapEvaluationDatasetDto,
  mapEvaluationRunDto,
  mapEvaluationSummaryDto,
  mapFeedbackDto,
  mapDashboardDto,
  mapIndexStateDto,
  mapJobDto,
  mapKnowledgeBaseDto,
  mapMessageDto,
  mapRetrievalDto,
  mapRetrievalAuditDto,
  mapSessionDto,
  mapSettingsDto,
  mapSourceReferenceDto,
  unwrapApiEnvelope,
  type JobSnapshot,
} from '@/api/mappers'
import {
  AppError,
  type ChatStreamResult,
  type ChatStreamStart,
  type RetrievalAudit,
  type SourceReference,
} from '@/types'

export interface RealAdapterDependencies {
  httpClient?: HttpClient
  pollIntervalMs?: number
}

function mapList<T>(
  value: unknown,
  mapper: (item: unknown) => T,
  resource: string,
): T[] {
  if (!Array.isArray(value)) {
    throw new AppError(
      'API_CONTRACT_INVALID',
      '后端响应与前端契约不一致。',
      `${resource} 列表不是数组。`,
      { kind: 'parse' },
    )
  }
  return value.map(mapper)
}

function eventRecord(value: unknown): Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    throw new AppError('STREAM_EVENT_INVALID', '后端返回了无效流式事件。', null, {
      kind: 'parse',
    })
  }
  return value as Record<string, unknown>
}

function eventString(value: Record<string, unknown>, field: string): string {
  const candidate = value[field]
  if (typeof candidate !== 'string' || !candidate) {
    throw new AppError('STREAM_EVENT_INVALID', `流式事件缺少 ${field}。`, null, {
      kind: 'parse',
    })
  }
  return candidate
}

function wait(milliseconds: number, signal: AbortSignal): Promise<void> {
  if (signal.aborted) {
    return Promise.reject(
      new AppError('REQUEST_CANCELLED', '请求已取消。', null, {
        kind: 'cancelled',
      }),
    )
  }
  return new Promise<void>((resolve, reject) => {
    const timeoutId = window.setTimeout(() => {
      signal.removeEventListener('abort', cancel)
      resolve()
    }, milliseconds)
    const cancel = (): void => {
      window.clearTimeout(timeoutId)
      signal.removeEventListener('abort', cancel)
      reject(
        new AppError('REQUEST_CANCELLED', '请求已取消。', null, {
          kind: 'cancelled',
        }),
      )
    }
    signal.addEventListener('abort', cancel, { once: true })
  })
}

export function createRealAdapter(
  config: ApiConfig,
  dependencies: RealAdapterDependencies = {},
): AppApi {
  const http =
    dependencies.httpClient ??
    new HttpClient(config, { accessToken: getRuntimeAccessToken })
  const pollIntervalMs = dependencies.pollIntervalMs ?? 350

  async function getEnvelope(path: string, signal?: AbortSignal): Promise<unknown> {
    const requestOptions = signal === undefined ? {} : { signal }
    const response = await http.request<unknown>(path, requestOptions)
    return unwrapApiEnvelope(response.data)
  }

  async function fetchJob(jobId: string, signal?: AbortSignal): Promise<JobSnapshot> {
    return mapJobDto(
      await getEnvelope(`/api/jobs/${encodeURIComponent(jobId)}`, signal),
    )
  }

  async function runChatStream(
    path: string,
    json: unknown,
    handlers: Parameters<AppApi['streamChat']>[1],
  ): Promise<ChatStreamResult> {
    let started: ChatStreamStart | null = null
    let sources: SourceReference[] = []
    let retrieval: RetrievalAudit | null = null
    let sourcesReceived = false
    let done = false
    await http.streamNdjson(path, { json, signal: handlers.signal }, (raw) => {
      const event = eventRecord(raw)
      const type = eventString(event, 'type')
      if (type === 'start') {
        if (started !== null) {
          throw new AppError(
            'STREAM_EVENT_ORDER_INVALID',
            '流式响应重复发送 start 事件。',
            null,
            { kind: 'parse' },
          )
        }
        started = {
          sessionId: eventString(event, 'session_id'),
          userMessageId: eventString(event, 'user_message_id'),
          assistantMessageId: eventString(event, 'assistant_message_id'),
          retry: event.retry === true,
          requestedMode: mapRetrievalAuditDto(event).requestedMode,
        }
        handlers.onStart(started)
        return
      }
      if (started === null) {
        throw new AppError(
          'STREAM_EVENT_ORDER_INVALID',
          '流式响应未先发送 start 事件。',
          null,
          { kind: 'parse' },
        )
      }
      if (type === 'retrieval') {
        if (retrieval !== null || sourcesReceived || done) {
          throw new AppError(
            'STREAM_EVENT_ORDER_INVALID',
            '流式检索事件顺序无效。',
            null,
            { kind: 'parse' },
          )
        }
        retrieval = mapRetrievalAuditDto(event)
        handlers.onRetrieval(retrieval)
        return
      }
      if (type === 'delta') {
        if (retrieval === null || sourcesReceived) {
          throw new AppError(
            'STREAM_EVENT_ORDER_INVALID',
            '正文增量必须位于 retrieval 与 sources 事件之间。',
            null,
            { kind: 'parse' },
          )
        }
        handlers.onDelta(eventString(event, 'content'))
        return
      }
      if (type === 'sources') {
        if (retrieval === null || sourcesReceived) {
          throw new AppError(
            'STREAM_EVENT_ORDER_INVALID',
            'sources 事件顺序无效。',
            null,
            { kind: 'parse' },
          )
        }
        if (!Array.isArray(event.sources)) {
          throw new AppError('STREAM_EVENT_INVALID', 'sources 事件格式无效。', null, {
            kind: 'parse',
          })
        }
        sources = event.sources.map(mapSourceReferenceDto)
        retrieval = mapRetrievalAuditDto(event)
        sourcesReceived = true
        handlers.onSources(sources)
        return
      }
      if (type === 'error') {
        const status = typeof event.code === 'number' ? event.code : null
        throw new AppError(
          typeof event.error_code === 'string'
            ? event.error_code
            : 'CHAT_STREAM_FAILED',
          eventString(event, 'message'),
          null,
          { kind: 'application', status },
        )
      }
      if (type === 'done') {
        if (retrieval === null || !sourcesReceived || done) {
          throw new AppError(
            'STREAM_EVENT_ORDER_INVALID',
            'done 事件必须紧随 sources 事件。',
            null,
            { kind: 'parse' },
          )
        }
        const assistantMessageId = eventString(event, 'assistant_message_id')
        if (assistantMessageId !== started.assistantMessageId) {
          throw new AppError(
            'STREAM_EVENT_ID_MISMATCH',
            '流式完成事件与当前回答不匹配。',
            null,
            { kind: 'parse' },
          )
        }
        retrieval = mapRetrievalAuditDto(event)
        done = true
        return
      }
      throw new AppError(
        'STREAM_EVENT_TYPE_UNKNOWN',
        `不支持的流式事件：${type}`,
        null,
        { kind: 'parse' },
      )
    })
    if (started === null || retrieval === null || !done) {
      throw new AppError('STREAM_UNEXPECTED_EOF', '流式连接在完成事件前中断。', null, {
        kind: 'parse',
      })
    }
    const completedStart = started as ChatStreamStart
    const completedRetrieval = retrieval as RetrievalAudit
    return {
      sessionId: completedStart.sessionId,
      userMessageId: completedStart.userMessageId,
      assistantMessageId: completedStart.assistantMessageId,
      sources,
      ...completedRetrieval,
    }
  }

  const adapter: AppApi = {
    async getSettings(options) {
      return mapSettingsDto(await getEnvelope('/api/settings', options?.signal))
    },

    async updateSettings(input) {
      const response = await http.request<unknown>('/api/settings', {
        method: 'PUT',
        json: {
          chat_model: input.chatModel,
          retrieval_top_k: input.topK,
          retrieval_score_threshold: input.scoreThreshold,
          rag_context_max_chars: input.maxContextCharacters,
          web_search_enabled: input.webSearchEnabled,
          default_retrieval_mode: input.defaultRetrievalMode,
          retrieval_min_evidence_count: input.minimumEvidenceCount,
          retrieval_freshness_terms: input.freshnessTerms,
        },
      })
      return mapSettingsDto(unwrapApiEnvelope(response.data))
    },

    async getDashboard(options = {}) {
      const response = await http.request<unknown>('/api/dashboard', {
        query: {
          knowledge_base_id: options.knowledgeBaseId,
          window_days: options.windowDays ?? 7,
          recent_limit: options.recentLimit ?? 5,
        },
        ...(options.signal === undefined ? {} : { signal: options.signal }),
      })
      return mapDashboardDto(unwrapApiEnvelope(response.data))
    },

    async listKnowledgeBases(options) {
      const data = await getEnvelope('/api/knowledge-bases', options?.signal)
      return mapList(data, mapKnowledgeBaseDto, '知识库')
    },

    async getKnowledgeBase(id, options) {
      const data = await getEnvelope(
        `/api/knowledge-bases/${encodeURIComponent(id)}`,
        options?.signal,
      )
      return mapKnowledgeBaseDto(data)
    },

    async createKnowledgeBase(input) {
      const response = await http.request<unknown>('/api/knowledge-bases', {
        method: 'POST',
        json: {
          name: input.name.trim(),
          description: input.description.trim() || null,
          web_access_policy: input.webAccessPolicy,
        },
      })
      return mapKnowledgeBaseDto(unwrapApiEnvelope(response.data))
    },

    async updateKnowledgeBase(id, input) {
      const response = await http.request<unknown>(
        `/api/knowledge-bases/${encodeURIComponent(id)}`,
        {
          method: 'PATCH',
          json: {
            name: input.name.trim(),
            description: input.description.trim() || null,
            web_access_policy: input.webAccessPolicy,
          },
        },
      )
      return mapKnowledgeBaseDto(unwrapApiEnvelope(response.data))
    },

    async deleteKnowledgeBase(id) {
      const response = await http.request<unknown>(
        `/api/knowledge-bases/${encodeURIComponent(id)}`,
        { method: 'DELETE' },
      )
      unwrapApiEnvelope(response.data)
    },

    async listFiles(knowledgeBaseId, options) {
      const response = await http.request<unknown>('/api/files', {
        query: { knowledge_base_id: knowledgeBaseId },
        ...(options?.signal === undefined ? {} : { signal: options.signal }),
      })
      return mapList(unwrapApiEnvelope(response.data), mapFileDto, '文件')
    },

    async getFile(id) {
      return mapFileDto(await getEnvelope(`/api/files/${encodeURIComponent(id)}`))
    },

    async addFile(knowledgeBaseId, input) {
      const formData = new FormData()
      formData.set('knowledge_base_id', knowledgeBaseId)
      formData.set('file', input.file, input.file.name)
      const response = await http.request<unknown>('/api/files/upload', {
        method: 'POST',
        formData,
      })
      return mapFileDto(unwrapApiEnvelope(response.data))
    },

    async processFile(id, handlers) {
      const submission = await http.request<unknown>(
        `/api/files/${encodeURIComponent(id)}/process`,
        { method: 'POST', signal: handlers.signal },
      )
      let job = mapJobDto(unwrapApiEnvelope(submission.data))
      handlers.onProgress(job.progress)

      while (!['SUCCEEDED', 'FAILED', 'CANCELLED'].includes(job.status)) {
        await wait(pollIntervalMs, handlers.signal)
        job = await fetchJob(job.id, handlers.signal)
        handlers.onProgress(job.progress)
      }

      if (job.status === 'SUCCEEDED') {
        return mapFileDto(
          await getEnvelope(`/api/files/${encodeURIComponent(id)}`, handlers.signal),
        )
      }
      if (job.status === 'CANCELLED') {
        throw new AppError('REQUEST_CANCELLED', '文件处理已取消。', null, {
          kind: 'cancelled',
        })
      }
      throw new AppError(
        'FILE_PROCESSING_FAILED',
        job.errorMessage ?? '文件处理失败。',
        null,
        { kind: 'application' },
      )
    },

    async deleteFile(id) {
      const response = await http.request<unknown>(
        `/api/files/${encodeURIComponent(id)}`,
        { method: 'DELETE' },
      )
      unwrapApiEnvelope(response.data)
    },

    async listSessions(options = {}) {
      const response = await http.request<unknown>('/api/sessions', {
        query: {
          knowledge_base_id: options.knowledgeBaseId,
          limit: options.limit ?? 50,
          offset: options.offset ?? 0,
        },
        ...(options.signal === undefined ? {} : { signal: options.signal }),
      })
      return mapList(unwrapApiEnvelope(response.data), mapSessionDto, '会话')
    },
    async getSession(id, knowledgeBaseId) {
      return mapSessionDto(
        await getEnvelope(
          `/api/sessions/${encodeURIComponent(id)}?knowledge_base_id=${encodeURIComponent(knowledgeBaseId)}`,
        ),
      )
    },
    async createSession(knowledgeBaseId) {
      const response = await http.request<unknown>('/api/sessions', {
        method: 'POST',
        json: { knowledge_base_id: knowledgeBaseId, title: '新会话' },
      })
      return mapSessionDto(unwrapApiEnvelope(response.data))
    },
    async updateSession(id, knowledgeBaseId, title) {
      const response = await http.request<unknown>(
        `/api/sessions/${encodeURIComponent(id)}`,
        {
          method: 'PATCH',
          query: { knowledge_base_id: knowledgeBaseId },
          json: { title: title.trim() },
        },
      )
      return mapSessionDto(unwrapApiEnvelope(response.data))
    },
    async deleteSession(id, knowledgeBaseId) {
      const response = await http.request<unknown>(
        `/api/sessions/${encodeURIComponent(id)}`,
        {
          method: 'DELETE',
          query: { knowledge_base_id: knowledgeBaseId },
        },
      )
      unwrapApiEnvelope(response.data)
    },
    async getMessages(sessionId, knowledgeBaseId, options = {}) {
      const response = await http.request<unknown>(
        `/api/sessions/${encodeURIComponent(sessionId)}/messages`,
        {
          query: {
            knowledge_base_id: knowledgeBaseId,
            limit: options.limit ?? 200,
            offset: options.offset ?? 0,
          },
          ...(options.signal === undefined ? {} : { signal: options.signal }),
        },
      )
      return mapList(unwrapApiEnvelope(response.data), mapMessageDto, '消息')
    },
    async updateMessageFeedback(sessionId, messageId, knowledgeBaseId, feedback) {
      const response = await http.request<unknown>(
        `/api/sessions/${encodeURIComponent(sessionId)}/messages/${encodeURIComponent(messageId)}/feedback`,
        {
          method: 'PUT',
          query: { knowledge_base_id: knowledgeBaseId },
          json: { value: feedback },
        },
      )
      return mapFeedbackDto(unwrapApiEnvelope(response.data))
    },
    async streamChat(request, handlers) {
      return runChatStream(
        '/api/chat/stream',
        {
          knowledge_base_id: request.knowledgeBaseId,
          session_id: request.sessionId,
          question: request.question.trim(),
          ...(request.topK === undefined ? {} : { top_k: request.topK }),
          mode: request.mode,
        },
        handlers,
      )
    },
    async retryChat(request, handlers) {
      return runChatStream(
        `/api/chat/messages/${encodeURIComponent(request.assistantMessageId)}/retry/stream`,
        {
          knowledge_base_id: request.knowledgeBaseId,
          session_id: request.sessionId,
          ...(request.topK === undefined ? {} : { top_k: request.topK }),
          mode: request.mode,
        },
        handlers,
      )
    },
    async cancelChat(sessionId, assistantMessageId, knowledgeBaseId) {
      const response = await http.request<unknown>(
        `/api/chat/messages/${encodeURIComponent(assistantMessageId)}/cancel`,
        {
          method: 'POST',
          json: {
            knowledge_base_id: knowledgeBaseId,
            session_id: sessionId,
          },
        },
      )
      unwrapApiEnvelope(response.data)
    },
    async executeRetrieval(request, options) {
      const response = await http.request<unknown>('/api/retrieval', {
        method: 'POST',
        json: {
          knowledge_base_id: request.knowledgeBaseId,
          query: request.query.trim(),
          top_k: request.topK,
          score_threshold: request.scoreThreshold,
        },
        ...(options?.signal === undefined ? {} : { signal: options.signal }),
      })
      return mapRetrievalDto(unwrapApiEnvelope(response.data))
    },
    async listIndexStates(knowledgeBaseId, signal) {
      const response = await http.request<unknown>('/api/indexes', {
        query: { knowledge_base_id: knowledgeBaseId },
        ...(signal === undefined ? {} : { signal }),
      })
      return mapList(unwrapApiEnvelope(response.data), mapIndexStateDto, '索引状态')
    },
    async submitIndexRebuild(knowledgeBaseId) {
      const response = await http.request<unknown>(
        `/api/knowledge-bases/${encodeURIComponent(knowledgeBaseId)}/rebuild`,
        { method: 'POST' },
      )
      return mapJobDto(unwrapApiEnvelope(response.data))
    },
    getJob: fetchJob,
    async cancelJob(id) {
      const response = await http.request<unknown>(
        `/api/jobs/${encodeURIComponent(id)}/cancel`,
        { method: 'POST' },
      )
      return mapJobDto(unwrapApiEnvelope(response.data))
    },
    async abortBuilding(knowledgeBaseId) {
      const response = await http.request<unknown>(
        `/api/knowledge-bases/${encodeURIComponent(knowledgeBaseId)}/abort-building`,
        { method: 'POST' },
      )
      unwrapApiEnvelope(response.data)
    },
    async rollbackKnowledgeBaseIndex(knowledgeBaseId) {
      const response = await http.request<unknown>(
        `/api/knowledge-bases/${encodeURIComponent(knowledgeBaseId)}/rollback`,
        { method: 'POST' },
      )
      unwrapApiEnvelope(response.data)
    },
    async cleanupKnowledgeBaseIndexes(knowledgeBaseId, options) {
      const response = await http.request<unknown>(
        `/api/knowledge-bases/${encodeURIComponent(knowledgeBaseId)}/cleanup-retired`,
        {
          method: 'POST',
          json: {
            cleanup_previous: options.cleanupPrevious,
            cleanup_orphans: options.cleanupOrphans,
          },
        },
      )
      return mapJobDto(unwrapApiEnvelope(response.data))
    },
    async listEvaluationDatasets() {
      const response = await http.request<unknown>('/api/evaluation-datasets', {
        query: { limit: 100, offset: 0 },
      })
      const page = eventRecord(unwrapApiEnvelope(response.data))
      return mapList(page.items, mapEvaluationDatasetDto, '评测数据集')
    },
    async uploadEvaluationDataset(input) {
      const formData = new FormData()
      formData.set('name', input.name.trim())
      formData.set('description', input.description.trim())
      formData.set('dataset_file', input.file, input.file.name)
      const response = await http.request<unknown>('/api/evaluation-datasets', {
        method: 'POST',
        formData,
      })
      return mapEvaluationDatasetDto(unwrapApiEnvelope(response.data))
    },
    async getEvaluationSummary() {
      return mapEvaluationSummaryDto(await getEnvelope('/api/evaluations/summary'))
    },
    async listEvaluationRuns() {
      const response = await http.request<unknown>('/api/evaluations', {
        query: { limit: 100, offset: 0 },
      })
      const page = eventRecord(unwrapApiEnvelope(response.data))
      return mapList(page.items, mapEvaluationRunDto, '评测运行')
    },
    async createEvaluationRun(input) {
      const response = await http.request<unknown>('/api/evaluations/runs', {
        method: 'POST',
        json: {
          dataset_id: input.datasetId,
          knowledge_base_id: input.knowledgeBaseId,
          run_name: input.name.trim(),
          mode: input.mode,
          top_k: input.topK,
          score_threshold: input.scoreThreshold,
          max_calls: input.maxCalls,
          max_generation_tokens: input.maxGenerationTokens,
          max_runtime_seconds: input.maxRuntimeSeconds,
        },
      })
      return mapEvaluationRunDto(unwrapApiEnvelope(response.data))
    },
    async getEvaluationRun(id, signal) {
      return mapEvaluationRunDto(
        await getEnvelope(`/api/evaluations/${encodeURIComponent(id)}`, signal),
      )
    },
    async listEvaluationCases(id, options = {}) {
      const response = await http.request<unknown>(
        `/api/evaluations/${encodeURIComponent(id)}/cases`,
        {
          query: {
            failed_only: options.failedOnly ?? false,
            limit: options.limit ?? 200,
            offset: options.offset ?? 0,
          },
        },
      )
      const page = eventRecord(unwrapApiEnvelope(response.data))
      return mapList(page.items, mapEvaluationCaseDto, '评测案例')
    },
  }

  return adapter
}
