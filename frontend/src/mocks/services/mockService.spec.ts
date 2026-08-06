import { beforeEach, describe, expect, it, vi } from 'vitest'

import { resetMockState } from '@/mocks/reset'
import * as service from '@/mocks/services/mockService'
import { AppError, type ChatRequest } from '@/types'

const chatRequest: ChatRequest = {
  sessionId: 'session-001',
  knowledgeBaseId: 'kb-product',
  question: '如何配置混合检索？',
  topK: 5,
  mode: 'knowledge_only',
}

function streamHandlers(
  onDelta: (chunk: string) => void = () => undefined,
  signal = new AbortController().signal,
) {
  return {
    signal,
    onStart: () => undefined,
    onRetrieval: () => undefined,
    onDelta,
    onSources: () => undefined,
  }
}

describe('Mock Service', () => {
  beforeEach(() => {
    vi.stubEnv('VITE_MOCK_DELAY_SCALE', '0')
    resetMockState()
  })

  it('supports knowledge base CRUD and deterministic reset', async () => {
    const initial = await service.listKnowledgeBases()
    const created = await service.createKnowledgeBase({
      name: '发布资料中心',
      description: '发布流程和材料',
      webAccessPolicy: 'inherit',
    })
    expect((await service.listKnowledgeBases())[0]?.id).toBe(created.id)

    const updated = await service.updateKnowledgeBase(created.id, {
      name: '发布资料中心 2',
      description: '更新后的说明',
      webAccessPolicy: 'deny',
    })
    expect(updated.name).toBe('发布资料中心 2')

    await service.deleteKnowledgeBase(created.id)
    expect(
      (await service.listKnowledgeBases()).some((item) => item.id === created.id),
    ).toBe(false)

    resetMockState()
    expect(await service.listKnowledgeBases()).toEqual(initial)
  })

  it('returns cloned values that cannot mutate fixtures', async () => {
    const first = await service.listKnowledgeBases()
    const originalName = first[0]?.name
    if (first[0]) first[0].name = '外部污染'
    expect((await service.listKnowledgeBases())[0]?.name).toBe(originalName)
  })

  it('runs the file state machine to success', async () => {
    const file = await service.addFile('kb-product', {
      file: new File(['x'.repeat(72_000)], '新增产品规范.txt', {
        type: 'text/plain',
      }),
    })
    const progress: number[] = []
    const completed = await service.processFile(file.id, {
      signal: new AbortController().signal,
      onProgress: (value) => progress.push(value),
    })
    expect(progress).toEqual([4, 18, 38, 62, 84, 100])
    expect(completed.status).toBe('SUCCESS')
    expect(completed.chunkCount).toBeGreaterThan(0)
  })

  it('keeps deterministic parser failure details and supports retry', async () => {
    const failed = (await service.listFiles('kb-product')).find(
      (file) => file.fileName === '损坏的技术文档.pdf',
    )
    expect(failed).toBeDefined()
    if (!failed) return

    await expect(
      service.processFile(failed.id, {
        signal: new AbortController().signal,
        onProgress: () => undefined,
      }),
    ).rejects.toMatchObject({
      code: 'FILE_PROCESSING_FAILED',
      detail: 'PDF parsing failed: invalid xref table',
    })
    expect((await service.getFile(failed.id)).status).toBe('FAILED')
  })

  it('cancels file processing without leaking PROCESSING state', async () => {
    const file = await service.addFile('kb-product', {
      file: new File(['x'.repeat(48_000)], '可取消文档.pdf', {
        type: 'application/pdf',
      }),
    })
    const controller = new AbortController()
    await expect(
      service.processFile(file.id, {
        signal: controller.signal,
        onProgress: (progress) => {
          if (progress === 4) controller.abort()
        },
      }),
    ).rejects.toMatchObject({ name: 'AbortError' })
    expect(await service.getFile(file.id)).toMatchObject({
      status: 'PENDING',
      progress: 0,
    })
  })

  it('streams chat with five mapped sources and supports no-source answers', async () => {
    const chunks: string[] = []
    const response = await service.streamChat(
      chatRequest,
      streamHandlers((chunk) => chunks.push(chunk)),
    )
    const history = await service.getMessages('session-001', 'kb-product')
    const assistant = history.find(
      (message) => message.id === response.assistantMessageId,
    )
    expect(chunks.join('')).toBe(assistant?.content)
    expect(response.sources).toHaveLength(5)
    expect(response.sources.map((source) => source.chunkId)).toEqual(
      assistant?.sources.map((source) => source.chunkId),
    )

    const noSources = await service.streamChat(
      { ...chatRequest, question: '量子航海协议是否存在？' },
      streamHandlers(),
    )
    expect(noSources.sources).toHaveLength(0)
    const updatedHistory = await service.getMessages('session-001', 'kb-product')
    expect(
      updatedHistory.find((message) => message.id === noSources.assistantMessageId)
        ?.content,
    ).toContain('没有检索到')
  })

  it('surfaces model failure and honors chat cancellation', async () => {
    await expect(
      service.streamChat({ ...chatRequest, question: '触发失败' }, streamHandlers()),
    ).rejects.toMatchObject({ code: 'MODEL_REQUEST_FAILED' })

    const controller = new AbortController()
    await expect(
      service.streamChat(
        chatRequest,
        streamHandlers(() => controller.abort(), controller.signal),
      ),
    ).rejects.toMatchObject({ name: 'AbortError' })
  })

  it('rebuilds indexes, reports seven steps and rejects invalid cleanup', async () => {
    const active = (await service.listIndexes()).find(
      (index) => index.lifecycle === 'active',
    )
    expect(active).toBeDefined()
    if (!active) return
    const snapshots: number[] = []
    const rebuilt = await service.rebuildIndex(active.id, {
      signal: new AbortController().signal,
      onProgress: (snapshot) => {
        expect(snapshot.steps).toHaveLength(7)
        snapshots.push(snapshot.progress)
      },
    })
    expect(snapshots.at(-1)).toBe(100)
    expect(rebuilt.generation).not.toBe(active.generation)
    await expect(service.cleanupIndex(rebuilt.id)).rejects.toBeInstanceOf(AppError)
  })

  it('restores evaluation state when a run is cancelled', async () => {
    const draft = (await service.listEvaluations()).find(
      (task) => task.status === 'DRAFT',
    )
    expect(draft).toBeDefined()
    if (!draft) return
    const controller = new AbortController()
    await expect(
      service.runEvaluation(draft.id, {
        signal: controller.signal,
        onProgress: () => controller.abort(),
      }),
    ).rejects.toMatchObject({ name: 'AbortError' })
    const restored = (await service.listEvaluations()).find(
      (task) => task.id === draft.id,
    )
    expect(restored).toMatchObject({ status: 'DRAFT', progress: 0 })
  })

  it('provides a deterministic session deletion failure', async () => {
    await expect(service.deleteSession('session-006', 'kb-help')).rejects.toMatchObject(
      { code: 'SESSION_DELETE_FAILED' },
    )
  })
})
