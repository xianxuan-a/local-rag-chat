import { apiClient } from '@/api/client'

export const dashboardApi = {
  getSnapshot: (options: Parameters<typeof apiClient.getDashboard>[0] = {}) =>
    apiClient.getDashboard(options),
}
