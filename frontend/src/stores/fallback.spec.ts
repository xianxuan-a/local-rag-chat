import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { knowledgeBaseApi } from '@/api/knowledgeBaseApi'
import { resetMockState } from '@/mocks/reset'
import { useKnowledgeBaseStore } from '@/stores/knowledgeBase'
import { useSessionStore } from '@/stores/session'
import { AppError } from '@/types'

describe('shared store fallback behavior', () => {
  beforeEach(() => {
    vi.stubEnv('VITE_MOCK_DELAY_SCALE', '0')
    resetMockState()
    setActivePinia(createPinia())
  })

  it('selects the next knowledge base after deleting the current one', async () => {
    const store = useKnowledgeBaseStore()
    await store.load()
    const removedId = store.currentId
    await store.remove(removedId)
    expect(store.currentId).not.toBe(removedId)
    expect(store.current).not.toBeNull()
  })

  it('never keeps a deleted current ID when the post-delete reload fails', async () => {
    const store = useKnowledgeBaseStore()
    await store.load()
    const removedId = store.currentId
    vi.spyOn(knowledgeBaseApi, 'list').mockRejectedValueOnce(
      new AppError('NETWORK_UNREACHABLE', '服务不可达'),
    )

    await store.remove(removedId)

    expect(store.items.some((item) => item.id === removedId)).toBe(false)
    expect(store.currentId).not.toBe(removedId)
    expect(store.loaded).toBe(false)
  })

  it('selects the next session after deleting the current one', async () => {
    const store = useSessionStore()
    await store.load()
    const removedId = store.currentId
    await store.remove(removedId)
    expect(store.currentId).not.toBe(removedId)
    expect(store.current).not.toBeNull()
  })
})
