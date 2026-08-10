import type {
  ChatMessage,
  ChatRequest,
  ChatRetryRequest,
  ChatStreamResult,
  ChatStreamStart,
  RetrievalAudit,
  ChatSession,
  DashboardSnapshot,
  AppSettings,
  AppSettingsInput,
  EvaluationCase,
  EvaluationDataset,
  EvaluationRun,
  EvaluationRunInput,
  EvaluationSummary,
  FileRecord,
  FileRecordPage,
  FileUploadInput,
  IndexState,
  DurableJob,
  KnowledgeBase,
  KnowledgeBaseInput,
  RetrievalRequest,
  RetrievalResponse,
  RebuildSnapshot,
  AdminUserPage,
  AdminUserUpdate,
  UserAdminAuditEventPage,
  AuthenticatedUser,
} from '@/types'

export interface ChatStreamHandlers {
  signal: AbortSignal
  onStart: (event: ChatStreamStart) => void
  onRetrieval: (audit: RetrievalAudit) => void
  onDelta: (delta: string) => void
  onSources: (sources: ChatMessage['sources']) => void
}

export interface ProgressHandlers {
  signal: AbortSignal
  onProgress: (progress: number) => void
}

export interface RebuildHandlers {
  signal: AbortSignal
  onProgress: (snapshot: RebuildSnapshot) => void
}

export interface RequestOptions {
  signal?: AbortSignal
}

export interface AppApi {
  listUsers(options?: {
    query?: string
    role?: 'ADMIN' | 'USER'
    isActive?: boolean
    limit?: number
    offset?: number
    signal?: AbortSignal
  }): Promise<AdminUserPage>
  updateUser(id: string, input: AdminUserUpdate): Promise<AuthenticatedUser>
  listUserAuditEvents(options?: {
    targetUserId?: string
    limit?: number
    offset?: number
    signal?: AbortSignal
  }): Promise<UserAdminAuditEventPage>

  getSettings(options?: RequestOptions): Promise<AppSettings>
  updateSettings(input: AppSettingsInput): Promise<AppSettings>

  getDashboard(options?: {
    knowledgeBaseId?: string
    windowDays?: number
    recentLimit?: number
    signal?: AbortSignal
  }): Promise<DashboardSnapshot>

  listKnowledgeBases(options?: RequestOptions): Promise<KnowledgeBase[]>
  getKnowledgeBase(id: string, options?: RequestOptions): Promise<KnowledgeBase>
  createKnowledgeBase(input: KnowledgeBaseInput): Promise<KnowledgeBase>
  updateKnowledgeBase(id: string, input: KnowledgeBaseInput): Promise<KnowledgeBase>
  deleteKnowledgeBase(id: string): Promise<void>

  listFiles(knowledgeBaseId: string, options?: RequestOptions): Promise<FileRecord[]>
  listFilesPage(
    knowledgeBaseId: string,
    options?: { limit?: number; offset?: number; signal?: AbortSignal },
  ): Promise<FileRecordPage>
  getFile(id: string): Promise<FileRecord>
  addFile(knowledgeBaseId: string, input: FileUploadInput): Promise<FileRecord>
  processFile(id: string, handlers: ProgressHandlers): Promise<FileRecord>
  deleteFile(id: string): Promise<void>

  listSessions(options?: {
    knowledgeBaseId?: string
    limit?: number
    offset?: number
    signal?: AbortSignal
  }): Promise<ChatSession[]>
  getSession(id: string, knowledgeBaseId: string): Promise<ChatSession>
  createSession(knowledgeBaseId: string): Promise<ChatSession>
  updateSession(
    id: string,
    knowledgeBaseId: string,
    title: string,
  ): Promise<ChatSession>
  deleteSession(id: string, knowledgeBaseId: string): Promise<void>
  getMessages(
    sessionId: string,
    knowledgeBaseId: string,
    options?: { limit?: number; offset?: number; signal?: AbortSignal },
  ): Promise<ChatMessage[]>
  updateMessageFeedback(
    sessionId: string,
    messageId: string,
    knowledgeBaseId: string,
    feedback: ChatMessage['feedback'],
  ): Promise<ChatMessage['feedback']>
  streamChat(
    request: ChatRequest,
    handlers: ChatStreamHandlers,
  ): Promise<ChatStreamResult>
  retryChat(
    request: ChatRetryRequest,
    handlers: ChatStreamHandlers,
  ): Promise<ChatStreamResult>
  cancelChat(
    sessionId: string,
    assistantMessageId: string,
    knowledgeBaseId: string,
  ): Promise<void>

  executeRetrieval(
    request: RetrievalRequest,
    options?: RequestOptions,
  ): Promise<RetrievalResponse>

  listIndexStates(knowledgeBaseId?: string, signal?: AbortSignal): Promise<IndexState[]>
  submitIndexRebuild(knowledgeBaseId: string): Promise<DurableJob>
  getJob(id: string, signal?: AbortSignal): Promise<DurableJob>
  cancelJob(id: string): Promise<DurableJob>
  abortBuilding(knowledgeBaseId: string): Promise<void>
  rollbackKnowledgeBaseIndex(knowledgeBaseId: string): Promise<void>
  cleanupKnowledgeBaseIndexes(
    knowledgeBaseId: string,
    options: { cleanupPrevious: boolean; cleanupOrphans: boolean },
  ): Promise<DurableJob>

  listEvaluationDatasets(): Promise<EvaluationDataset[]>
  uploadEvaluationDataset(input: {
    name: string
    description: string
    file: File
  }): Promise<EvaluationDataset>
  getEvaluationSummary(): Promise<EvaluationSummary>
  listEvaluationRuns(): Promise<EvaluationRun[]>
  createEvaluationRun(input: EvaluationRunInput): Promise<EvaluationRun>
  getEvaluationRun(id: string, signal?: AbortSignal): Promise<EvaluationRun>
  listEvaluationCases(
    id: string,
    options?: { failedOnly?: boolean; limit?: number; offset?: number },
  ): Promise<EvaluationCase[]>
}
