import { describe, expect, it, vi } from 'vitest'

import { createRealAdapter } from '@/api/adapters/realAdapter'
import type { ApiConfig } from '@/api/config'
import { HttpClient } from '@/api/http'
import * as mockService from '@/mocks/services/mockService'

const config: ApiConfig = {
  mode: 'real',
  baseUrl: 'http://127.0.0.1:8000',
  timeoutMs: 2_000,
}

const knowledgeBaseDto = {
  id: 'b29ba188-1da8-4b58-8ac8-a0cf14650ab7',
  owner_id: 'e1b3fb85-aa62-47e5-b163-e9537dad8c46',
  name: 'Real API 知识库',
  description: '来自 FastAPI',
  web_access_policy: 'inherit',
  file_count: 1,
  chunk_count: 4,
  embedding_model: 'text-embedding-v4',
  status: 'READY',
  created_at: '2026-07-27T01:00:00Z',
  updated_at: '2026-07-27T01:01:00Z',
}

const retrievalAuditDto = {
  requested_mode: 'knowledge_only',
  effective_mode: 'knowledge_only',
  web_search_triggered: false,
  web_search_status: 'not_requested',
  web_trigger_reason: null,
  knowledge_source_count: 1,
  web_source_count: 0,
  fallback_reason: null,
}

const fileDto = {
  id: '0a995cd2-dcc9-4f9f-b85b-1842ef1c4ec2',
  knowledge_base_id: knowledgeBaseDto.id,
  original_name: '规范.txt',
  stored_name: '0a995cd2.txt',
  file_path: 'uploads/0a995cd2.txt',
  file_type: '.txt',
  file_size: 12,
  md5: '0123456789abcdef0123456789abcdef',
  status: 'SUCCESS',
  chunk_count: 4,
  progress: 100,
  has_active_vectors: true,
  active_index_config_hash: 'hash',
  error_message: null,
  processing_job_id: null,
  last_successful_indexed_at: '2026-07-27T01:02:00Z',
  embedding_provider: 'dashscope',
  embedding_model: 'text-embedding-v4',
  embedding_dimension: 1024,
  vector_metric: 'cosine',
  collection_name: 'kb_active',
  created_at: '2026-07-27T01:00:00Z',
  updated_at: '2026-07-27T01:02:00Z',
}

function envelope(data: unknown, status = 200): Response {
  return new Response(JSON.stringify({ code: 0, message: 'success', data }), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function requestUrl(input: RequestInfo | URL): string {
  if (typeof input === 'string') return input
  return input instanceof URL ? input.href : input.url
}

describe('Real API adapter', () => {
  it('maps the real Dashboard aggregate and sends an explicit scope', async () => {
    const mockDashboard = vi.spyOn(mockService, 'getDashboard')
    const fetcher = vi.fn<typeof fetch>((input) => {
      const url = new URL(requestUrl(input))
      expect(url.pathname).toBe('/api/dashboard')
      expect(url.searchParams.get('knowledge_base_id')).toBe(knowledgeBaseDto.id)
      expect(url.searchParams.get('window_days')).toBe('7')
      return Promise.resolve(
        envelope({
          generated_at: '2026-07-27T02:00:00Z',
          time_zone: 'UTC',
          window_days: 7,
          knowledge_base_id: knowledgeBaseDto.id,
          metrics: {
            knowledge_bases: 1,
            files_total: 1,
            files_success: 1,
            files_in_progress: 0,
            files_failed: 0,
            chunks: 4,
            sessions: 1,
            user_questions: 2,
            assistant_answers: 2,
            active_indexes: 1,
            building_indexes: 0,
          },
          trend: [
            {
              date: '2026-07-27',
              uploads: 1,
              questions: 2,
              failed_files: 0,
              index_operations: 1,
              evaluation_runs: 1,
            },
          ],
          file_statuses: [
            { status: 'PENDING', count: 0 },
            { status: 'PROCESSING', count: 0 },
            { status: 'SUCCESS', count: 1 },
            { status: 'FAILED', count: 0 },
          ],
          recent_files: [
            {
              id: fileDto.id,
              knowledge_base_id: knowledgeBaseDto.id,
              knowledge_base_name: knowledgeBaseDto.name,
              file_name: fileDto.original_name,
              file_type: fileDto.file_type,
              status: 'SUCCESS',
              chunk_count: 4,
              updated_at: '2026-07-27T01:02:00Z',
            },
          ],
          recent_sessions: [
            {
              id: 'b64f2578-07cb-4b85-9fa9-f2daff21f370',
              knowledge_base_id: knowledgeBaseDto.id,
              knowledge_base_name: knowledgeBaseDto.name,
              title: '真实会话',
              preview: '真实问题',
              message_count: 4,
              updated_at: '2026-07-27T01:03:00Z',
            },
          ],
          recent_index_jobs: [
            {
              id: '418a4b4c-600d-4614-b4cd-97538d380dfc',
              knowledge_base_id: knowledgeBaseDto.id,
              knowledge_base_name: knowledgeBaseDto.name,
              job_type: 'KB_REBUILD',
              status: 'SUCCEEDED',
              stage: 'SUCCEEDED',
              progress: 100,
              error_message: null,
              created_at: '2026-07-27T01:04:00Z',
              finished_at: '2026-07-27T01:05:00Z',
            },
          ],
          recent_evaluations: [],
          runtime: {
            chat_configured: false,
            missing_chat_configuration: ['CHAT_MODEL'],
            embedding_key_configured: true,
          },
          section_errors: {},
        }),
      )
    })
    const adapter = createRealAdapter(config, {
      httpClient: new HttpClient(config, { fetcher }),
    })

    const snapshot = await adapter.getDashboard({
      knowledgeBaseId: knowledgeBaseDto.id,
    })

    expect(snapshot.metrics.find((item) => item.id === 'files')?.value).toBe(1)
    expect(snapshot.trend[0]?.indexOperations).toBe(1)
    expect(snapshot.recentFiles[0]?.fileName).toBe('规范.txt')
    expect(snapshot.recentIndexJobs[0]?.status).toBe('SUCCEEDED')
    expect(snapshot.runtime.missingChatConfiguration).toEqual(['CHAT_MODEL'])
    expect(mockDashboard).not.toHaveBeenCalled()
  })

  it('maps persistent settings, PATCH updates, and direct retrieval', async () => {
    const methods: string[] = []
    const fetcher = vi.fn<typeof fetch>((input, requestInit) => {
      const url = new URL(requestUrl(input))
      methods.push(`${requestInit?.method ?? 'GET'} ${url.pathname}`)
      if (url.pathname === '/api/settings') {
        return Promise.resolve(
          envelope({
            chat_model: 'qwen3-max',
            retrieval_top_k: 8,
            retrieval_score_threshold: 0.4,
            rag_context_max_chars: 24000,
            web_search_enabled: false,
            default_retrieval_mode: 'knowledge_first',
            retrieval_min_evidence_count: 1,
            retrieval_freshness_terms: ['今天', '最新'],
            web_search_provider: 'disabled',
            web_search_provider_configured: false,
            web_search_allowed_for_current_user: true,
            embedding_provider: 'dashscope',
            embedding_model: 'text-embedding-v4',
            embedding_dimension: 1024,
            vector_metric: 'cosine',
            dashscope_api_key_configured: true,
            source: 'persistent',
            updated_at: '2026-07-27T01:00:00Z',
          }),
        )
      }
      if (url.pathname === `/api/knowledge-bases/${knowledgeBaseDto.id}`) {
        return Promise.resolve(
          envelope({ ...knowledgeBaseDto, name: '更新后的知识库' }),
        )
      }
      if (url.pathname === '/api/retrieval') {
        return Promise.resolve(
          envelope({
            result_count: 1,
            query_time_ms: 12,
            results: [
              {
                rank: 1,
                score: 0.91,
                file_id: fileDto.id,
                file_name: fileDto.original_name,
                chunk_id: 'chunk-real',
                content: '真实完整正文',
                metadata: { page: 2 },
              },
            ],
          }),
        )
      }
      return Promise.resolve(envelope(null))
    })
    const adapter = createRealAdapter(config, {
      httpClient: new HttpClient(config, { fetcher }),
    })

    await expect(adapter.getSettings()).resolves.toMatchObject({
      chatModel: 'qwen3-max',
      source: 'persistent',
      apiKeyConfigured: true,
    })
    await expect(
      adapter.updateKnowledgeBase(knowledgeBaseDto.id, {
        name: '更新后的知识库',
        description: '',
        webAccessPolicy: 'inherit',
      }),
    ).resolves.toMatchObject({ name: '更新后的知识库' })
    await expect(
      adapter.executeRetrieval({
        knowledgeBaseId: knowledgeBaseDto.id,
        query: '真实查询',
        topK: 5,
        scoreThreshold: 0.2,
      }),
    ).resolves.toMatchObject({
      resultCount: 1,
      results: [{ content: '真实完整正文', score: 0.91 }],
    })
    expect(methods).toContain('PATCH /api/knowledge-bases/' + knowledgeBaseDto.id)
    expect(methods).toContain('POST /api/retrieval')
  })

  it('uses the actual knowledge-base and multipart file routes', async () => {
    const fetcher = vi.fn<typeof fetch>((input, requestInit) => {
      const url = new URL(requestUrl(input))
      if (url.pathname === '/api/knowledge-bases' && requestInit?.method === 'POST') {
        return Promise.resolve(envelope(knowledgeBaseDto, 201))
      }
      if (url.pathname === '/api/files/upload') {
        return Promise.resolve(envelope(fileDto, 201))
      }
      return Promise.resolve(envelope([knowledgeBaseDto]))
    })
    const httpClient = new HttpClient(config, {
      fetcher,
      accessToken: () => 'runtime-token',
    })
    const adapter = createRealAdapter(config, { httpClient })

    await expect(adapter.listKnowledgeBases()).resolves.toHaveLength(1)
    await expect(
      adapter.createKnowledgeBase({
        name: 'Real API 知识库',
        description: '来自 FastAPI',
        webAccessPolicy: 'inherit',
      }),
    ).resolves.toMatchObject({ id: knowledgeBaseDto.id })
    await expect(
      adapter.addFile(knowledgeBaseDto.id, {
        file: new File(['real content'], '规范.txt', { type: 'text/plain' }),
      }),
    ).resolves.toMatchObject({ id: fileDto.id, chunkCount: 4 })

    const uploadCall = fetcher.mock.calls.find(([input]) =>
      requestUrl(input).endsWith('/api/files/upload'),
    )
    const uploadHeaders = new Headers(uploadCall?.[1]?.headers)
    expect(uploadCall?.[1]?.body).toBeInstanceOf(FormData)
    expect(uploadHeaders.has('Content-Type')).toBe(false)
    expect(uploadHeaders.get('Authorization')).toBe('Bearer runtime-token')
  })

  it('polls the durable Job and refetches the persisted file result', async () => {
    let jobReads = 0
    const paths: string[] = []
    const fetcher = vi.fn<typeof fetch>((input, requestInit) => {
      const url = new URL(requestUrl(input))
      paths.push(`${requestInit?.method ?? 'GET'} ${url.pathname}`)
      if (url.pathname.endsWith('/process')) {
        return Promise.resolve(
          envelope(
            {
              id: 'a50f693c-bbca-45b0-bb48-06f8f8137c4f',
              status: 'QUEUED',
              progress: 0,
              error_message: null,
            },
            202,
          ),
        )
      }
      if (url.pathname.startsWith('/api/jobs/')) {
        jobReads += 1
        return Promise.resolve(
          envelope({
            id: 'a50f693c-bbca-45b0-bb48-06f8f8137c4f',
            status: jobReads === 1 ? 'RUNNING' : 'SUCCEEDED',
            progress: jobReads === 1 ? 60 : 100,
            error_message: null,
          }),
        )
      }
      return Promise.resolve(envelope(fileDto))
    })
    const adapter = createRealAdapter(config, {
      httpClient: new HttpClient(config, { fetcher }),
      pollIntervalMs: 0,
    })
    const progress: number[] = []

    const completed = await adapter.processFile(fileDto.id, {
      signal: new AbortController().signal,
      onProgress: (value) => progress.push(value),
    })

    expect(completed.status).toBe('SUCCESS')
    expect(progress).toEqual([0, 60, 100])
    expect(paths).toContain(`POST /api/files/${fileDto.id}/process`)
    expect(paths).toContain(`GET /api/jobs/a50f693c-bbca-45b0-bb48-06f8f8137c4f`)
    expect(paths.at(-1)).toBe(`GET /api/files/${fileDto.id}`)
  })

  it('stops polling without cancelling the durable Job when the caller leaves', async () => {
    const controller = new AbortController()
    const paths: string[] = []
    const fetcher = vi.fn<typeof fetch>((input, requestInit) => {
      const url = new URL(requestUrl(input))
      paths.push(`${requestInit?.method ?? 'GET'} ${url.pathname}`)
      if (url.pathname.endsWith('/process')) {
        return Promise.resolve(
          envelope(
            {
              id: 'a50f693c-bbca-45b0-bb48-06f8f8137c4f',
              status: 'QUEUED',
              progress: 0,
              error_message: null,
            },
            202,
          ),
        )
      }
      return Promise.resolve(
        envelope({
          id: 'a50f693c-bbca-45b0-bb48-06f8f8137c4f',
          status: 'CANCELLED',
          progress: 0,
          error_message: null,
        }),
      )
    })
    const adapter = createRealAdapter(config, {
      httpClient: new HttpClient(config, { fetcher }),
      pollIntervalMs: 10,
    })

    await expect(
      adapter.processFile(fileDto.id, {
        signal: controller.signal,
        onProgress: () => controller.abort(),
      }),
    ).rejects.toMatchObject({ kind: 'cancelled' })
    expect(paths).not.toContain(
      'POST /api/jobs/a50f693c-bbca-45b0-bb48-06f8f8137c4f/cancel',
    )
  })

  it('surfaces a network failure without calling the Mock service', async () => {
    const mockList = vi.spyOn(mockService, 'listKnowledgeBases')
    const adapter = createRealAdapter(config, {
      httpClient: new HttpClient(config, {
        fetcher: vi
          .fn<typeof fetch>()
          .mockRejectedValue(new TypeError('connection refused')),
      }),
    })

    await expect(adapter.listKnowledgeBases()).rejects.toMatchObject({
      kind: 'network',
      code: 'NETWORK_UNREACHABLE',
    })
    expect(mockList).not.toHaveBeenCalled()
  })

  it('maps sessions, messages, feedback, stop and the complete chat stream', async () => {
    const sessionId = '4a5c38ca-e2f0-4b1d-82b8-c3d2ed95c8e0'
    const userMessageId = 'db09caf6-85c5-42fd-bf5d-834049de78ef'
    const assistantMessageId = '13d76139-41ac-4441-98db-3c25d27796d8'
    const sessionDto = {
      id: sessionId,
      knowledge_base_id: knowledgeBaseDto.id,
      title: '真实会话',
      preview: '真实回答',
      message_count: 2,
      created_at: '2026-07-27T01:00:00Z',
      updated_at: '2026-07-27T01:01:00Z',
    }
    const sourceDto = {
      citation_number: 1,
      source_type: 'knowledge_base',
      reference: '[K1]',
      title: fileDto.original_name,
      file_id: fileDto.id,
      file_name: fileDto.original_name,
      chunk_id: 'chunk-real',
      url: null,
      domain: null,
      published_at: null,
      accessed_at: null,
      content_preview: '真实分块',
      score: 0.91,
      metadata: { page: 2 },
    }
    const messageDto = {
      id: assistantMessageId,
      session_id: sessionId,
      role: 'assistant',
      content: '真实回答 [K1]',
      references: [sourceDto],
      status: 'complete',
      error_code: null,
      error_message: null,
      reply_to_message_id: userMessageId,
      feedback: 'like',
      created_at: '2026-07-27T01:00:01Z',
      updated_at: '2026-07-27T01:00:02Z',
      ...retrievalAuditDto,
    }
    const requests: string[] = []
    const fetcher = vi.fn<typeof fetch>((input, requestInit) => {
      const url = new URL(requestUrl(input))
      requests.push(`${requestInit?.method ?? 'GET'} ${url.pathname}${url.search}`)
      if (url.pathname.endsWith('/messages') && requestInit?.method !== 'POST') {
        return Promise.resolve(envelope([messageDto]))
      }
      if (url.pathname.endsWith('/feedback')) {
        return Promise.resolve(
          envelope({
            message_id: assistantMessageId,
            value: 'like',
            updated_at: '2026-07-27T01:01:00Z',
          }),
        )
      }
      if (url.pathname.endsWith('/cancel')) {
        return Promise.resolve(
          envelope({
            session_id: sessionId,
            assistant_message_id: assistantMessageId,
            cancel_requested: true,
          }),
        )
      }
      if (url.pathname === '/api/chat/stream') {
        const ndjson = [
          {
            type: 'start',
            session_id: sessionId,
            user_message_id: userMessageId,
            assistant_message_id: assistantMessageId,
            retry: false,
            ...retrievalAuditDto,
          },
          {
            type: 'retrieval',
            session_id: sessionId,
            assistant_message_id: assistantMessageId,
            ...retrievalAuditDto,
          },
          {
            type: 'delta',
            assistant_message_id: assistantMessageId,
            content: '真实回答 [K1]',
          },
          {
            type: 'sources',
            assistant_message_id: assistantMessageId,
            sources: [sourceDto],
            ...retrievalAuditDto,
          },
          {
            type: 'done',
            session_id: sessionId,
            user_message_id: userMessageId,
            assistant_message_id: assistantMessageId,
            ...retrievalAuditDto,
          },
        ]
          .map((event) => JSON.stringify(event))
          .join('\n')
        return Promise.resolve(
          new Response(`${ndjson}\n`, {
            headers: { 'Content-Type': 'application/x-ndjson' },
          }),
        )
      }
      return Promise.resolve(envelope([sessionDto]))
    })
    const adapter = createRealAdapter(config, {
      httpClient: new HttpClient(config, { fetcher }),
    })

    await expect(
      adapter.listSessions({
        knowledgeBaseId: knowledgeBaseDto.id,
        limit: 10,
        offset: 5,
      }),
    ).resolves.toEqual([expect.objectContaining({ id: sessionId, messageCount: 2 })])
    await expect(adapter.getMessages(sessionId, knowledgeBaseDto.id)).resolves.toEqual([
      expect.objectContaining({
        id: assistantMessageId,
        replyToMessageId: userMessageId,
        feedback: 'like',
      }),
    ])
    await expect(
      adapter.updateMessageFeedback(
        sessionId,
        assistantMessageId,
        knowledgeBaseDto.id,
        'like',
      ),
    ).resolves.toBe('like')
    await expect(
      adapter.cancelChat(sessionId, assistantMessageId, knowledgeBaseDto.id),
    ).resolves.toBeUndefined()

    const deltas: string[] = []
    const starts: string[] = []
    const streamed = await adapter.streamChat(
      {
        sessionId,
        knowledgeBaseId: knowledgeBaseDto.id,
        question: '真实问题',
        topK: 4,
        mode: 'knowledge_only',
      },
      {
        signal: new AbortController().signal,
        onStart: (event) => starts.push(event.assistantMessageId),
        onRetrieval: () => undefined,
        onDelta: (delta) => deltas.push(delta),
        onSources: () => undefined,
      },
    )
    expect(starts).toEqual([assistantMessageId])
    expect(deltas).toEqual(['真实回答 [K1]'])
    expect(streamed).toMatchObject({
      sessionId,
      userMessageId,
      assistantMessageId,
      sources: [expect.objectContaining({ citationNumber: 1, metadata: { page: 2 } })],
      effectiveMode: 'knowledge_only',
    })
    expect(requests).toContain(
      `GET /api/sessions?knowledge_base_id=${knowledgeBaseDto.id}&limit=10&offset=5`,
    )
    expect(requests).toContain(`POST /api/chat/messages/${assistantMessageId}/cancel`)
  })

  it('rejects unknown stream events and abnormal EOF without Mock fallback', async () => {
    const mockStream = vi.spyOn(mockService, 'streamChat')
    const streamResponse = (body: string) =>
      Promise.resolve(
        new Response(body, {
          headers: { 'Content-Type': 'application/x-ndjson' },
        }),
      )
    const start = `${JSON.stringify({
      type: 'start',
      session_id: '4a5c38ca-e2f0-4b1d-82b8-c3d2ed95c8e0',
      user_message_id: 'db09caf6-85c5-42fd-bf5d-834049de78ef',
      assistant_message_id: '13d76139-41ac-4441-98db-3c25d27796d8',
      ...retrievalAuditDto,
    })}\n`
    const unknownAdapter = createRealAdapter(config, {
      httpClient: new HttpClient(config, {
        fetcher: vi
          .fn<typeof fetch>()
          .mockImplementation(() => streamResponse(`${start}{"type":"mystery"}\n`)),
      }),
    })
    const handlers = {
      signal: new AbortController().signal,
      onStart: () => undefined,
      onRetrieval: () => undefined,
      onDelta: () => undefined,
      onSources: () => undefined,
    }
    await expect(
      unknownAdapter.streamChat(
        {
          sessionId: '4a5c38ca-e2f0-4b1d-82b8-c3d2ed95c8e0',
          knowledgeBaseId: knowledgeBaseDto.id,
          question: '问题',
          mode: 'knowledge_only',
        },
        handlers,
      ),
    ).rejects.toMatchObject({ code: 'STREAM_EVENT_TYPE_UNKNOWN' })

    const eofAdapter = createRealAdapter(config, {
      httpClient: new HttpClient(config, {
        fetcher: vi.fn<typeof fetch>().mockImplementation(() => streamResponse(start)),
      }),
    })
    await expect(
      eofAdapter.streamChat(
        {
          sessionId: '4a5c38ca-e2f0-4b1d-82b8-c3d2ed95c8e0',
          knowledgeBaseId: knowledgeBaseDto.id,
          question: '问题',
          mode: 'knowledge_only',
        },
        handlers,
      ),
    ).rejects.toMatchObject({ code: 'STREAM_UNEXPECTED_EOF' })
    expect(mockStream).not.toHaveBeenCalled()
  })

  it('uses real index and evaluation endpoints without Mock fallback', async () => {
    const mockIndexes = vi.spyOn(mockService, 'listIndexes')
    const paths: string[] = []
    const job = {
      id: '61fdd7c3-bc23-483b-a433-5f3ec5eb2eb0',
      job_type: 'RAG_EVALUATION',
      status: 'SUCCEEDED',
      resource_type: 'KNOWLEDGE_BASE',
      resource_id: knowledgeBaseDto.id,
      resource_name_snapshot: knowledgeBaseDto.name,
      progress: 100,
      stage: 'SUCCEEDED',
      error_code: null,
      error_message: null,
      created_at: '2026-07-27T01:00:00Z',
      updated_at: '2026-07-27T01:01:00Z',
      finished_at: '2026-07-27T01:01:00Z',
    }
    const fetcher = vi.fn<typeof fetch>((input) => {
      const url = new URL(requestUrl(input))
      paths.push(url.pathname)
      if (url.pathname === '/api/indexes') {
        return Promise.resolve(
          envelope([
            {
              knowledge_base_id: knowledgeBaseDto.id,
              knowledge_base_name: knowledgeBaseDto.name,
              rebuild_status: 'IDLE',
              rebuild_run_id: null,
              building_started_at: null,
              latest_job: null,
              collections: [],
            },
          ]),
        )
      }
      if (url.pathname === '/api/evaluation-datasets') {
        return Promise.resolve(envelope({ items: [], total: 0, limit: 100, offset: 0 }))
      }
      if (url.pathname === '/api/evaluations/summary') {
        return Promise.resolve(
          envelope({
            run_count: 1,
            dataset_count: 0,
            status_counts: { SUCCEEDED: 1 },
          }),
        )
      }
      if (url.pathname === '/api/evaluations') {
        return Promise.resolve(
          envelope({
            items: [
              {
                job,
                dataset: null,
                mode: 'retrieval',
                run_name: '真实检索评测',
                outcome: 'SUCCESS',
                metrics: null,
              },
            ],
            total: 1,
            limit: 100,
            offset: 0,
          }),
        )
      }
      return Promise.resolve(envelope(null))
    })
    const adapter = createRealAdapter(config, {
      httpClient: new HttpClient(config, { fetcher }),
    })

    await expect(adapter.listIndexStates()).resolves.toHaveLength(1)
    await expect(adapter.listEvaluationDatasets()).resolves.toEqual([])
    await expect(adapter.getEvaluationSummary()).resolves.toMatchObject({
      runCount: 1,
      statusCounts: { SUCCEEDED: 1 },
    })
    await expect(adapter.listEvaluationRuns()).resolves.toMatchObject([
      { mode: 'retrieval', status: 'SUCCEEDED', dataset: null },
    ])
    expect(paths).toEqual([
      '/api/indexes',
      '/api/evaluation-datasets',
      '/api/evaluations/summary',
      '/api/evaluations',
    ])
    expect(mockIndexes).not.toHaveBeenCalled()
  })
})
