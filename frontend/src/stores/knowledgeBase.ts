import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { knowledgeBaseApi } from '@/api/knowledgeBaseApi'
import type { KnowledgeBase, KnowledgeBaseInput } from '@/types'

export const useKnowledgeBaseStore = defineStore('knowledgeBase', () => {
  const items = ref<KnowledgeBase[]>([])
  const currentId = ref('')
  const loading = ref(false)
  const loaded = ref(false)

  const current = computed(
    () => items.value.find((item) => item.id === currentId.value) ?? null,
  )

  async function load(force = false): Promise<void> {
    if (loaded.value && !force) return
    loading.value = true
    try {
      items.value = await knowledgeBaseApi.list()
      if (!items.value.some((item) => item.id === currentId.value)) {
        currentId.value = items.value[0]?.id ?? ''
      }
      loaded.value = true
    } finally {
      loading.value = false
    }
  }

  function setCurrent(id: string): void {
    if (items.value.some((item) => item.id === id)) currentId.value = id
  }

  function reset(): void {
    items.value = []
    currentId.value = ''
    loading.value = false
    loaded.value = false
  }

  async function create(input: KnowledgeBaseInput): Promise<KnowledgeBase> {
    const item = await knowledgeBaseApi.create(input)
    items.value.unshift(item)
    currentId.value = item.id
    return item
  }

  async function update(id: string, input: KnowledgeBaseInput): Promise<KnowledgeBase> {
    const updated = await knowledgeBaseApi.update(id, input)
    const index = items.value.findIndex((item) => item.id === id)
    if (index >= 0) items.value[index] = updated
    try {
      items.value = await knowledgeBaseApi.list()
      loaded.value = true
      return items.value.find((item) => item.id === id) ?? updated
    } catch {
      loaded.value = false
      return updated
    }
  }

  async function remove(id: string): Promise<void> {
    await knowledgeBaseApi.remove(id)
    const localRemaining = items.value.filter((item) => item.id !== id)
    try {
      items.value = await knowledgeBaseApi.list()
      loaded.value = true
    } catch {
      items.value = localRemaining
      loaded.value = false
    }
    if (!items.value.some((item) => item.id === currentId.value)) {
      currentId.value = items.value[0]?.id ?? ''
    }
  }

  return {
    items,
    currentId,
    current,
    loading,
    loaded,
    load,
    setCurrent,
    reset,
    create,
    update,
    remove,
  }
})
