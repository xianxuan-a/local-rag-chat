import { describe, expect, it } from 'vitest'

import type { ChatMessage, SourceReference } from '@/types'
import { latestAssistantSources } from '@/utils/chatSources'

function assistant(id: string, sources: SourceReference[]): ChatMessage {
  return {
    id,
    sessionId: 'session-1',
    role: 'assistant',
    content: id,
    createdAt: '2026-08-10T00:00:00+00:00',
    status: 'complete',
    sources,
    metrics: null,
    feedback: null,
    errorMessage: null,
    requestedMode: 'knowledge_only',
    effectiveMode: 'knowledge_only',
    webSearchTriggered: false,
    webSearchStatus: 'not_requested',
    webTriggerReason: null,
    knowledgeSourceCount: sources.length,
    webSourceCount: 0,
    fallbackReason: null,
  }
}

const source = {
  citationNumber: 1,
  sourceType: 'knowledge_base' as const,
  reference: 'K1',
  title: '旧来源',
  fileId: 'file-1',
  fileName: 'old.txt',
  chunkId: 'chunk-1',
  url: null,
  domain: null,
  publishedAt: null,
  accessedAt: null,
  contentPreview: 'old',
  score: 0.9,
  metadata: {},
}

describe('latestAssistantSources', () => {
  it('uses the latest assistant even when its source list is empty', () => {
    expect(
      latestAssistantSources([
        assistant('with-sources', [source]),
        assistant('without-sources', []),
      ]),
    ).toEqual({ messageId: 'without-sources', sources: [] })
  })

  it('returns no active source message when history has no assistant', () => {
    expect(latestAssistantSources([])).toEqual({ messageId: null, sources: [] })
  })
})
