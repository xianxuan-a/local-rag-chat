import { describe, expect, it } from 'vitest'

import {
  mapFileDto,
  mapEvaluationRunDto,
  mapIndexStateDto,
  mapKnowledgeBaseDto,
  mapMessageDto,
  mapSessionDto,
  unwrapApiEnvelope,
} from '@/api/mappers'
import { AppError } from '@/types'

const knowledgeBaseDto = {
  id: 'b29ba188-1da8-4b58-8ac8-a0cf14650ab7',
  owner_id: 'e1b3fb85-aa62-47e5-b163-e9537dad8c46',
  name: '真实知识库',
  description: null,
  web_access_policy: 'inherit',
  file_count: 1,
  chunk_count: 4,
  embedding_model: 'text-embedding-v4',
  status: 'READY',
  created_at: '2026-07-27T01:00:00Z',
  updated_at: '2026-07-27T01:01:00+00:00',
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

describe('Real API DTO mappers', () => {
  it('maps explicit snake_case fields without inventing values', () => {
    expect(mapKnowledgeBaseDto(knowledgeBaseDto)).toMatchObject({
      id: knowledgeBaseDto.id,
      description: '',
      fileCount: 1,
      chunkCount: 4,
      status: 'READY',
    })
    expect(mapFileDto(fileDto)).toMatchObject({
      fileName: '规范.txt',
      fileType: 'TXT',
      contentHash: 'md5:0123456789abcdef0123456789abcdef',
      chunkCount: 4,
      collectionName: 'kb_active',
    })
  })

  it('rejects missing required fields, unknown enums and ambiguous time', () => {
    expect(() =>
      mapKnowledgeBaseDto({ ...knowledgeBaseDto, file_count: undefined }),
    ).toThrowError(AppError)
    expect(() => mapFileDto({ ...fileDto, status: 'UNKNOWN' })).toThrowError(AppError)
    expect(() =>
      mapFileDto({ ...fileDto, updated_at: '2026-07-27 09:00:00' }),
    ).toThrowError(AppError)
  })

  it('unwraps only successful response envelopes', () => {
    expect(unwrapApiEnvelope({ code: 0, message: 'success', data: fileDto })).toBe(
      fileDto,
    )
    expect(() =>
      unwrapApiEnvelope({ code: 500, message: 'failed', data: null }),
    ).toThrowError(AppError)
  })

  it('maps server session aggregates and persisted message lifecycle fields', () => {
    const sessionId = '4a5c38ca-e2f0-4b1d-82b8-c3d2ed95c8e0'
    const userMessageId = 'db09caf6-85c5-42fd-bf5d-834049de78ef'
    expect(
      mapSessionDto({
        id: sessionId,
        knowledge_base_id: knowledgeBaseDto.id,
        title: '真实会话',
        preview: '部分回答',
        message_count: 2,
        created_at: '2026-07-27T01:00:00Z',
        updated_at: '2026-07-27T01:01:00Z',
      }),
    ).toMatchObject({ messageCount: 2, preview: '部分回答' })
    expect(
      mapMessageDto({
        id: '13d76139-41ac-4441-98db-3c25d27796d8',
        session_id: sessionId,
        role: 'assistant',
        content: '部分回答',
        references: [],
        status: 'failed',
        error_code: 'MODEL_UNAVAILABLE',
        error_message: '模型不可用',
        requested_mode: 'hybrid',
        effective_mode: 'knowledge_only',
        web_search_triggered: false,
        web_search_status: 'blocked_by_policy',
        web_trigger_reason: null,
        knowledge_source_count: 0,
        web_source_count: 0,
        fallback_reason: 'global_web_search_disabled',
        reply_to_message_id: userMessageId,
        feedback: null,
        created_at: '2026-07-27T01:00:01Z',
        updated_at: '2026-07-27T01:00:02Z',
      }),
    ).toMatchObject({
      status: 'failed',
      errorCode: 'MODEL_UNAVAILABLE',
      replyToMessageId: userMessageId,
    })
  })

  it('maps real index pointers and nullable evaluation metrics', () => {
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
    expect(
      mapIndexStateDto({
        knowledge_base_id: knowledgeBaseDto.id,
        knowledge_base_name: knowledgeBaseDto.name,
        rebuild_status: 'IDLE',
        rebuild_run_id: null,
        building_started_at: null,
        latest_job: null,
        collections: [
          {
            collection_name: 'kb_active',
            role: 'active',
            exists: true,
            lifecycle_status: 'ACTIVE',
            generation: 'G1',
            embedding_provider: 'dashscope',
            embedding_model: 'text-embedding-v4',
            embedding_dimension: 1024,
            distance_metric: 'cosine',
            embedding_config_hash: 'hash',
            file_count: 1,
            chunk_count: 4,
            safe_to_cleanup: false,
            cleanup_reason: '活动索引禁止清理',
            error: null,
          },
        ],
      }),
    ).toMatchObject({
      knowledgeBaseId: knowledgeBaseDto.id,
      collections: [
        {
          lifecycle: 'active',
          chunkCount: 4,
          safeToCleanup: false,
        },
      ],
    })
    expect(
      mapEvaluationRunDto({
        job,
        dataset: null,
        mode: 'retrieval',
        run_name: '检索基线',
        outcome: 'PARTIAL_SUCCESS',
        metrics: {
          retrieval: { hit_at_k: null, recall_at_k: null, mrr: null },
          generation_and_citations: null,
        },
      }),
    ).toMatchObject({
      mode: 'retrieval',
      outcome: 'PARTIAL_SUCCESS',
      dataset: null,
      metrics: {
        retrieval: { hit_at_k: null },
        generation_and_citations: null,
      },
    })
  })
})
