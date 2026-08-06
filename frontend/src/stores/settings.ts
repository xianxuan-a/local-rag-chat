import { defineStore } from 'pinia'
import { ref } from 'vue'

import { settingsApi } from '@/api/settingsApi'
import type { AppSettings, AppSettingsInput } from '@/types'

export const useSettingsStore = defineStore('settings', () => {
  const settings = ref<AppSettings | null>(null)
  const loading = ref(false)
  const saving = ref(false)
  const loaded = ref(false)

  async function load(force = false, signal?: AbortSignal): Promise<AppSettings> {
    if (loaded.value && !force && settings.value !== null) return settings.value
    loading.value = true
    try {
      const result = await settingsApi.get(signal === undefined ? {} : { signal })
      settings.value = result
      loaded.value = true
      return result
    } finally {
      loading.value = false
    }
  }

  async function save(input: AppSettingsInput): Promise<AppSettings> {
    saving.value = true
    try {
      await settingsApi.update(input)
      return await load(true)
    } finally {
      saving.value = false
    }
  }

  function reset(): void {
    settings.value = null
    loading.value = false
    saving.value = false
    loaded.value = false
  }

  return { settings, loading, saving, loaded, load, save, reset }
})
