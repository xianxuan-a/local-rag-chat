import { apiClient } from '@/api/client'
import type { RequestOptions } from '@/api/contracts'
import type { AppSettingsInput } from '@/types'

export const settingsApi = {
  get: (options?: RequestOptions) => apiClient.getSettings(options),
  update: (input: AppSettingsInput) => apiClient.updateSettings(input),
}
