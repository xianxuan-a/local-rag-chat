import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { sessionApi } from '@/api/sessionApi'
import { AppError, type ChatSession } from '@/types'

const PAGE_SIZE = 50

export const useSessionStore = defineStore('session', () => {
  const items = ref<ChatSession[]>([])
  const currentId = ref('')
  const loading = ref(false)
  const loadingMore = ref(false)
  const loaded = ref(false)
  const hasMore = ref(false)

  const current = computed(
    () => items.value.find((item) => item.id === currentId.value) ?? null,
  )

  async function load(force = false): Promise<void> {
    if (loaded.value && !force) return
    loading.value = true
    try {
      const previousCurrentId = currentId.value
      const page = await sessionApi.list({ limit: PAGE_SIZE, offset: 0 })
      items.value = page
      hasMore.value = page.length === PAGE_SIZE
      if (!items.value.some((item) => item.id === currentId.value)) {
        currentId.value = items.value[0]?.id ?? ''
      }
      if (items.value.some((item) => item.id === previousCurrentId)) {
        currentId.value = previousCurrentId
      }
      loaded.value = true
    } finally {
      loading.value = false
    }
  }

  async function loadMore(): Promise<void> {
    if (loadingMore.value || !hasMore.value) return
    loadingMore.value = true
    try {
      const page = await sessionApi.list({
        limit: PAGE_SIZE,
        offset: items.value.length,
      })
      const known = new Set(items.value.map((item) => item.id))
      items.value.push(...page.filter((item) => !known.has(item.id)))
      hasMore.value = page.length === PAGE_SIZE
    } finally {
      loadingMore.value = false
    }
  }

  function upsert(session: ChatSession): void {
    const index = items.value.findIndex((item) => item.id === session.id)
    if (index >= 0) items.value[index] = session
    else items.value.push(session)
    items.value.sort(
      (left, right) =>
        right.updatedAt.localeCompare(left.updatedAt) ||
        right.id.localeCompare(left.id),
    )
  }

  function setCurrent(id: string): boolean {
    if (!items.value.some((item) => item.id === id)) return false
    currentId.value = id
    return true
  }

  async function ensureCurrent(
    id: string,
    knowledgeBaseIds: string[],
  ): Promise<ChatSession | null> {
    const known = items.value.find((item) => item.id === id)
    if (known !== undefined) {
      currentId.value = id
      return known
    }
    for (const knowledgeBaseId of knowledgeBaseIds) {
      try {
        const session = await sessionApi.get(id, knowledgeBaseId)
        upsert(session)
        currentId.value = id
        return session
      } catch (caught) {
        if (
          caught instanceof AppError &&
          (caught.status === 404 || caught.code === 'SESSION_NOT_FOUND')
        ) {
          continue
        }
        throw caught
      }
    }
    return null
  }

  async function create(knowledgeBaseId: string): Promise<ChatSession> {
    const session = await sessionApi.create(knowledgeBaseId)
    upsert(session)
    currentId.value = session.id
    return session
  }

  async function updateTitle(
    id: string,
    knowledgeBaseId: string,
    title: string,
  ): Promise<ChatSession> {
    const session = await sessionApi.update(id, knowledgeBaseId, title)
    upsert(session)
    return session
  }

  async function remove(id: string, knowledgeBaseId?: string): Promise<void> {
    const target = items.value.find((item) => item.id === id)
    const ownerKnowledgeBaseId = knowledgeBaseId ?? target?.knowledgeBaseId
    if (ownerKnowledgeBaseId === undefined) {
      throw new AppError('SESSION_NOT_FOUND', '会话不存在或已被删除。')
    }
    await sessionApi.remove(id, ownerKnowledgeBaseId)
    items.value = items.value.filter((item) => item.id !== id)
    if (currentId.value === id) currentId.value = items.value[0]?.id ?? ''
  }

  function clearCurrent(): void {
    currentId.value = ''
  }

  return {
    items,
    currentId,
    current,
    loading,
    loadingMore,
    loaded,
    hasMore,
    load,
    loadMore,
    setCurrent,
    ensureCurrent,
    create,
    updateTitle,
    remove,
    clearCurrent,
  }
})
