import { describe, expect, it } from 'vitest'

import type { IndexCollection, IndexLifecycle } from '@/types'
import { getIndexActionAvailability } from '@/utils/indexRules'

function makeIndex(lifecycle: IndexLifecycle): IndexCollection {
  return {
    id: `index-${lifecycle}`,
    collectionName: `collection_${lifecycle}`,
    knowledgeBaseId: 'kb-product',
    lifecycle,
    generation: 'G12',
    fileCount: 10,
    chunkCount: 1_000,
    createdAt: '2026-07-26T10:42:00.000Z',
    config: {
      provider: 'DashScope',
      model: 'text-embedding-v4',
      dimension: 1024,
      normalization: true,
      metric: 'cosine',
      configHash: 'a45d8b661c2',
    },
  }
}

describe('index action availability', () => {
  it('enables rebuild and rollback only while idle', () => {
    const active = makeIndex('active')
    expect(getIndexActionAvailability(active, null, true)).toEqual({
      rebuild: true,
      rollback: true,
      terminate: false,
      cleanup: false,
    })
    expect(getIndexActionAvailability(active, active.id, true)).toEqual({
      rebuild: false,
      rollback: false,
      terminate: true,
      cleanup: false,
    })
  })

  it('enables termination for building and cleanup for old indexes', () => {
    expect(
      getIndexActionAvailability(makeIndex('building'), null, false),
    ).toMatchObject({ rebuild: false, terminate: true, cleanup: false })
    expect(
      getIndexActionAvailability(makeIndex('previous'), null, false),
    ).toMatchObject({ rollback: false, terminate: false, cleanup: true })
  })
})
