import type { AppApi } from '@/api/contracts'
import * as mockService from '@/mocks/services/mockService'
import { AppError } from '@/types'
import type {
  AuthenticatedUser,
  DurableJob,
  EvaluationDataset,
  EvaluationRun,
  IndexState,
  UserAdminAuditEvent,
} from '@/types'

const mockJobs = new Map<string, DurableJob>()
const mockDatasets: EvaluationDataset[] = []
const mockRuns: EvaluationRun[] = []
const mockUsers: AuthenticatedUser[] = [
  {
    id: 'mock-admin',
    username: 'mock-admin',
    email: 'mock-admin@example.com',
    role: 'ADMIN',
    isActive: true,
    mustChangePassword: false,
    createdAt: '2026-07-01T08:00:00+00:00',
  },
  {
    id: 'mock-user',
    username: 'knowledge-user',
    email: 'knowledge-user@example.com',
    role: 'USER',
    isActive: true,
    mustChangePassword: false,
    createdAt: '2026-07-02T08:00:00+00:00',
  },
]
const mockUserAuditEvents: UserAdminAuditEvent[] = []

function mockId(prefix: string): string {
  return `${prefix}-${globalThis.crypto.randomUUID()}`
}

function createMockJob(
  jobType: string,
  resourceId: string,
  resourceName: string,
): DurableJob {
  const now = new Date().toISOString()
  const job: DurableJob = {
    id: mockId('job'),
    jobType,
    status: 'SUCCEEDED',
    progress: 100,
    stage: 'SUCCEEDED',
    errorCode: null,
    errorMessage: null,
    createdAt: now,
    updatedAt: now,
    finishedAt: now,
    resourceId,
    resourceName,
  }
  mockJobs.set(job.id, job)
  return { ...job }
}

export const mockAdapter: AppApi = {
  listUsers(options = {}) {
    const query = options.query?.trim().toLocaleLowerCase() ?? ''
    const filtered = mockUsers.filter(
      (user) =>
        (!query ||
          user.username.toLocaleLowerCase().includes(query) ||
          user.email?.toLocaleLowerCase().includes(query)) &&
        (!options.role || user.role === options.role) &&
        (options.isActive === undefined || user.isActive === options.isActive),
    )
    const limit = options.limit ?? 50
    const offset = options.offset ?? 0
    return Promise.resolve({
      items: structuredClone(filtered.slice(offset, offset + limit)),
      total: filtered.length,
      limit,
      offset,
    })
  },
  updateUser(id, input) {
    const user = mockUsers.find((candidate) => candidate.id === id)
    if (!user) throw new AppError('USER_NOT_FOUND', '用户不存在。')
    const beforeState = { role: user.role, isActive: user.isActive }
    if (input.role !== undefined) user.role = input.role
    if (input.isActive !== undefined) user.isActive = input.isActive
    const afterState = { role: user.role, isActive: user.isActive }
    if (
      beforeState.role !== afterState.role ||
      beforeState.isActive !== afterState.isActive
    ) {
      mockUserAuditEvents.unshift({
        id: mockId('audit'),
        actorUserId: 'mock-admin',
        targetUserId: user.id,
        action: 'USER_UPDATED',
        beforeState,
        afterState,
        reason: input.reason?.trim() || null,
        requestId: globalThis.crypto.randomUUID(),
        createdAt: new Date().toISOString(),
      })
    }
    return Promise.resolve(structuredClone(user))
  },
  listUserAuditEvents(options = {}) {
    const filtered = options.targetUserId
      ? mockUserAuditEvents.filter(
          (event) => event.targetUserId === options.targetUserId,
        )
      : mockUserAuditEvents
    const limit = options.limit ?? 50
    const offset = options.offset ?? 0
    return Promise.resolve({
      items: structuredClone(filtered.slice(offset, offset + limit)),
      total: filtered.length,
      limit,
      offset,
    })
  },
  getSettings: mockService.getSettings,
  updateSettings: mockService.updateSettings,
  getDashboard: mockService.getDashboard,
  listKnowledgeBases: mockService.listKnowledgeBases,
  getKnowledgeBase: mockService.getKnowledgeBase,
  createKnowledgeBase: mockService.createKnowledgeBase,
  updateKnowledgeBase: mockService.updateKnowledgeBase,
  deleteKnowledgeBase: mockService.deleteKnowledgeBase,
  listFiles: mockService.listFiles,
  async listFilesPage(knowledgeBaseId, options = {}) {
    const files = await mockService.listFiles(
      knowledgeBaseId,
      options.signal === undefined ? {} : { signal: options.signal },
    )
    const limit = options.limit ?? 50
    const offset = options.offset ?? 0
    return {
      items: files.slice(offset, offset + limit),
      total: files.length,
      limit,
      offset,
    }
  },
  getFile: mockService.getFile,
  addFile: mockService.addFile,
  processFile: mockService.processFile,
  deleteFile: mockService.deleteFile,
  listSessions: mockService.listSessions,
  getSession: mockService.getSession,
  createSession: mockService.createSession,
  updateSession: mockService.updateSession,
  deleteSession: mockService.deleteSession,
  getMessages: mockService.getMessages,
  updateMessageFeedback: mockService.updateMessageFeedback,
  streamChat: mockService.streamChat,
  retryChat: mockService.retryChat,
  cancelChat: mockService.cancelChat,
  executeRetrieval: mockService.executeRetrieval,
  async listIndexStates(knowledgeBaseId) {
    const [collections, knowledgeBases] = await Promise.all([
      mockService.listIndexes(),
      mockService.listKnowledgeBases(),
    ])
    const grouped = new Map<string, IndexState>()
    for (const knowledgeBase of knowledgeBases) {
      if (knowledgeBaseId && knowledgeBase.id !== knowledgeBaseId) continue
      grouped.set(knowledgeBase.id, {
        knowledgeBaseId: knowledgeBase.id,
        knowledgeBaseName: knowledgeBase.name,
        rebuildStatus: 'IDLE',
        rebuildRunId: null,
        buildingStartedAt: null,
        collections: [],
        latestJob: null,
      })
    }
    for (const collection of collections) {
      grouped.get(collection.knowledgeBaseId)?.collections.push({
        ...collection,
        exists: true,
        safeToCleanup: ['previous', 'cleanup', 'orphan'].includes(collection.lifecycle),
        cleanupReason:
          collection.lifecycle === 'previous'
            ? '清理后将失去当前回滚版本'
            : 'Mock 后端会再次验证',
        error: null,
      })
    }
    return [...grouped.values()]
  },
  async submitIndexRebuild(knowledgeBaseId) {
    const knowledgeBase = await mockService.getKnowledgeBase(knowledgeBaseId)
    const active = (await mockService.listIndexes()).find(
      (item) => item.knowledgeBaseId === knowledgeBaseId && item.lifecycle === 'active',
    )
    if (active) {
      await mockService.rebuildIndex(active.id, {
        signal: new AbortController().signal,
        onProgress: () => undefined,
      })
    }
    return createMockJob('KB_REBUILD', knowledgeBaseId, knowledgeBase.name)
  },
  getJob(id) {
    const job = mockJobs.get(id)
    return job
      ? Promise.resolve({ ...job })
      : Promise.reject(new AppError('JOB_NOT_FOUND', 'Job 不存在。'))
  },
  cancelJob(id) {
    const job = mockJobs.get(id)
    if (!job) return Promise.reject(new AppError('JOB_NOT_FOUND', 'Job 不存在。'))
    if (!['SUCCEEDED', 'FAILED', 'CANCELLED'].includes(job.status)) {
      job.status = 'CANCELLED'
      job.stage = 'CANCELLED'
      job.finishedAt = new Date().toISOString()
    }
    return Promise.resolve({ ...job })
  },
  async abortBuilding() {},
  async rollbackKnowledgeBaseIndex(knowledgeBaseId) {
    const collections = await mockService.listIndexes()
    const active = collections.find(
      (item) => item.knowledgeBaseId === knowledgeBaseId && item.lifecycle === 'active',
    )
    if (active) await mockService.rollbackIndex(active.id)
  },
  async cleanupKnowledgeBaseIndexes(knowledgeBaseId, options) {
    const knowledgeBase = await mockService.getKnowledgeBase(knowledgeBaseId)
    const targets = (await mockService.listIndexes()).filter(
      (item) =>
        item.knowledgeBaseId === knowledgeBaseId &&
        ((options.cleanupPrevious && item.lifecycle === 'previous') ||
          (options.cleanupOrphans && item.lifecycle === 'orphan')),
    )
    for (const target of targets) await mockService.cleanupIndex(target.id)
    return createMockJob('KB_CLEANUP_RETIRED', knowledgeBaseId, knowledgeBase.name)
  },
  listEvaluationDatasets() {
    return Promise.resolve(mockDatasets.map((item) => ({ ...item })))
  },
  async uploadEvaluationDataset(input) {
    const now = new Date().toISOString()
    const raw = await input.file.text()
    const dataset: EvaluationDataset = {
      id: mockId('dataset'),
      ownerId: 'mock-user',
      name: input.name.trim(),
      description: input.description.trim(),
      originalFilename: input.file.name,
      sha256: `mock-${raw.length}`,
      sizeBytes: input.file.size,
      caseCount: raw.split(/\r?\n/u).filter(Boolean).length,
      createdAt: now,
      updatedAt: now,
    }
    mockDatasets.unshift(dataset)
    return { ...dataset }
  },
  getEvaluationSummary() {
    const statusCounts: Record<string, number> = {}
    for (const run of mockRuns) {
      statusCounts[run.status] = (statusCounts[run.status] ?? 0) + 1
    }
    return Promise.resolve({
      runCount: mockRuns.length,
      datasetCount: mockDatasets.length,
      statusCounts,
    })
  },
  listEvaluationRuns() {
    return Promise.resolve(mockRuns.map((item) => ({ ...item })))
  },
  async createEvaluationRun(input) {
    const dataset = mockDatasets.find((item) => item.id === input.datasetId)
    if (!dataset) throw new AppError('DATASET_NOT_FOUND', '评测数据集不存在。')
    const knowledgeBase = await mockService.getKnowledgeBase(input.knowledgeBaseId)
    const now = new Date().toISOString()
    const run: EvaluationRun = {
      id: mockId('evaluation'),
      name: input.name,
      mode: input.mode,
      knowledgeBaseId: input.knowledgeBaseId,
      knowledgeBaseName: knowledgeBase.name,
      dataset: { ...dataset },
      status: 'SUCCEEDED',
      progress: 100,
      stage: 'SUCCEEDED',
      outcome: 'SUCCESS',
      metrics: {
        retrieval: {
          evaluated_cases: dataset.caseCount,
          hit_at_k: null,
          recall_at_k: null,
          mrr: null,
          average_latency_seconds: 0.01,
        },
        generation_and_citations: null,
      },
      errorCode: null,
      errorMessage: null,
      createdAt: now,
      finishedAt: now,
    }
    mockRuns.unshift(run)
    const job = createMockJob('RAG_EVALUATION', run.knowledgeBaseId, knowledgeBase.name)
    mockJobs.delete(job.id)
    mockJobs.set(run.id, { ...job, id: run.id })
    return { ...run }
  },
  getEvaluationRun(id) {
    const run = mockRuns.find((item) => item.id === id)
    return run
      ? Promise.resolve({ ...run })
      : Promise.reject(new AppError('EVALUATION_NOT_FOUND', '评测运行不存在。'))
  },
  listEvaluationCases() {
    return Promise.resolve([])
  },
}
