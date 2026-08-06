import { apiClient } from '@/api/client'
import type { EvaluationRunInput } from '@/types'

export const evaluationApi = {
  listDatasets: () => apiClient.listEvaluationDatasets(),
  uploadDataset: (input: { name: string; description: string; file: File }) =>
    apiClient.uploadEvaluationDataset(input),
  getSummary: () => apiClient.getEvaluationSummary(),
  listRuns: () => apiClient.listEvaluationRuns(),
  createRun: (input: EvaluationRunInput) => apiClient.createEvaluationRun(input),
  getRun: (id: string, signal?: AbortSignal) => apiClient.getEvaluationRun(id, signal),
  listCases: (
    id: string,
    options?: { failedOnly?: boolean; limit?: number; offset?: number },
  ) => apiClient.listEvaluationCases(id, options),
  cancel: (id: string) => apiClient.cancelJob(id),
}
