export type ApiMode = 'mock' | 'real'

export type UserRole = 'ADMIN' | 'USER'

export interface AuthenticatedUser {
  id: string
  username: string
  email: string | null
  role: UserRole
  isActive: boolean
  mustChangePassword: boolean
  createdAt: string
}

export interface AuthSession {
  accessToken: string
  tokenType: 'bearer'
  expiresIn: number
  user: AuthenticatedUser
}

export type FileStatus = 'PENDING' | 'PROCESSING' | 'SUCCESS' | 'FAILED'

export type KnowledgeBaseStatus = 'READY' | 'BUILDING' | 'FAILED' | 'EMPTY'

export type IndexLifecycle = 'active' | 'previous' | 'building' | 'cleanup' | 'orphan'

export type EvaluationStatus = 'DRAFT' | 'RUNNING' | 'COMPLETED' | 'FAILED'

export type ChatMessageStatus = 'complete' | 'streaming' | 'failed' | 'cancelled'

export type AnswerFeedback = 'like' | 'dislike' | null

export type RetrievalMode = 'knowledge_only' | 'knowledge_first' | 'hybrid'

export type KnowledgeBaseWebPolicy = 'inherit' | 'allow' | 'deny'

export type WebSearchStatus =
  | 'not_requested'
  | 'blocked_by_policy'
  | 'not_configured'
  | 'success'
  | 'partial'
  | 'failed'
  | 'timeout'
  | 'rate_limited'
  | 'query_rejected'

export interface RetrievalAudit {
  requestedMode: RetrievalMode
  effectiveMode: RetrievalMode
  webSearchTriggered: boolean
  webSearchStatus: WebSearchStatus
  webTriggerReason: string | null
  knowledgeSourceCount: number
  webSourceCount: number
  fallbackReason: string | null
}

export type AppErrorKind =
  'cancelled' | 'timeout' | 'network' | 'http' | 'parse' | 'config' | 'application'

export interface AppErrorShape {
  code: string
  message: string
  detail: string | null
  status: number | null
  kind: AppErrorKind
  details?: unknown
  requestId?: string | null
  retryAfterSeconds?: number | null
  originalCause?: unknown
}

export class AppError extends Error implements AppErrorShape {
  readonly code: string
  readonly detail: string | null
  readonly status: number | null
  readonly kind: AppErrorKind
  readonly details?: unknown
  readonly requestId?: string | null
  readonly retryAfterSeconds?: number | null
  readonly originalCause?: unknown

  constructor(
    code: string,
    message: string,
    detail: string | null = null,
    options: {
      status?: number | null
      kind?: AppErrorKind
      details?: unknown
      requestId?: string | null
      retryAfterSeconds?: number | null
      cause?: unknown
    } = {},
  ) {
    super(message)
    this.name = 'AppError'
    this.code = code
    this.detail = detail
    this.status = options.status ?? null
    this.kind = options.kind ?? 'application'
    if ('details' in options) this.details = options.details
    if ('requestId' in options) this.requestId = options.requestId
    if ('retryAfterSeconds' in options) {
      this.retryAfterSeconds = options.retryAfterSeconds
    }
    if ('cause' in options) this.originalCause = options.cause
  }
}

export interface KnowledgeBase {
  id: string
  name: string
  description: string
  fileCount: number
  chunkCount: number
  embeddingModel: string
  updatedAt: string
  status: KnowledgeBaseStatus
  webAccessPolicy: KnowledgeBaseWebPolicy
}

export interface KnowledgeBaseInput {
  name: string
  description: string
  webAccessPolicy: KnowledgeBaseWebPolicy
}

export interface FileRecord {
  id: string
  knowledgeBaseId: string
  fileName: string
  fileType: string
  fileSize: number
  status: FileStatus
  progress: number
  chunkCount: number
  hasActiveVectors: boolean
  activeIndexConfigHash: string | null
  lastSuccessfulIndexedAt: string | null
  errorMessage: string | null
  createdAt: string
  updatedAt: string
  filePath: string
  contentHash: string
  embeddingProvider: string
  embeddingModel: string
  embeddingDimension: number
  vectorMetric: string
  collectionName: string | null
  processingDuration: number | null
}

export interface FileUploadInput {
  file: File
}

export interface SourceReference {
  citationNumber: number
  sourceType: 'knowledge_base' | 'web'
  reference: string
  title: string
  fileId: string | null
  fileName: string | null
  chunkId: string | null
  url: string | null
  domain: string | null
  publishedAt: string | null
  accessedAt: string | null
  contentPreview: string
  content?: string
  score: number
  metadata: Record<string, string | number | boolean | null>
}

export interface AnswerMetrics {
  retrievalMs: number
  generationMs: number
  totalMs: number
  promptTokens: number
  completionTokens: number
}

export interface ChatMessage extends RetrievalAudit {
  id: string
  sessionId: string
  role: 'user' | 'assistant' | 'system'
  content: string
  createdAt: string
  status: ChatMessageStatus
  sources: SourceReference[]
  metrics: AnswerMetrics | null
  feedback: AnswerFeedback
  errorMessage: string | null
  errorCode?: string | null
  replyToMessageId?: string | null
  updatedAt?: string
}

export interface ChatSession {
  id: string
  knowledgeBaseId: string
  title: string
  preview: string
  createdAt: string
  updatedAt: string
  messageCount: number
}

export interface ChatRequest {
  sessionId: string
  knowledgeBaseId: string
  question: string
  topK?: number
  mode: RetrievalMode
}

export interface ChatStreamResult extends RetrievalAudit {
  sessionId: string
  userMessageId: string
  assistantMessageId: string
  sources: SourceReference[]
}

export interface ChatRetryRequest {
  sessionId: string
  knowledgeBaseId: string
  assistantMessageId: string
  topK?: number
  mode: RetrievalMode
}

export interface ChatStreamStart {
  sessionId: string
  userMessageId: string
  assistantMessageId: string
  retry: boolean
  requestedMode: RetrievalMode
}

export interface RetrievalRequest {
  knowledgeBaseId: string
  query: string
  topK: number
  scoreThreshold: number | null
}

export interface RetrievalResult {
  rank: number
  score: number
  fileName: string
  fileId: string
  chunkId: string
  content: string
  metadata: Record<string, string | number | boolean | null>
}

export interface RetrievalResponse {
  queryTimeMs: number
  resultCount: number
  results: RetrievalResult[]
}

export interface IndexConfig {
  provider: string
  model: string
  dimension: number
  normalization: boolean
  metric: string
  configHash: string
}

export interface IndexCollection {
  id: string
  collectionName: string
  knowledgeBaseId: string
  lifecycle: IndexLifecycle
  generation: string
  fileCount: number
  chunkCount: number
  createdAt: string
  config: IndexConfig
  exists?: boolean
  safeToCleanup?: boolean
  cleanupReason?: string | null
  error?: string | null
}

export type DurableJobStatus =
  'QUEUED' | 'RUNNING' | 'CANCEL_REQUESTED' | 'SUCCEEDED' | 'FAILED' | 'CANCELLED'

export interface DurableJob {
  id: string
  jobType: string
  status: DurableJobStatus
  progress: number
  stage: string | null
  errorCode: string | null
  errorMessage: string | null
  createdAt: string
  updatedAt: string
  finishedAt: string | null
  resourceId: string | null
  resourceName: string | null
}

export interface IndexState {
  knowledgeBaseId: string
  knowledgeBaseName: string
  rebuildStatus: string
  rebuildRunId: string | null
  buildingStartedAt: string | null
  collections: IndexCollection[]
  latestJob: DurableJob | null
}

export interface RebuildSnapshot {
  collectionId: string
  progress: number
  stepIndex: number
  steps: string[]
  status: 'idle' | 'building' | 'completed' | 'cancelled' | 'failed'
  processedFiles: number
  totalFiles: number
}

export interface DashboardMetric {
  id: 'knowledgeBases' | 'files' | 'chunks' | 'questions' | 'sessions' | 'activeIndexes'
  label: string
  value: number
  note: string
}

export interface DashboardTrendPoint {
  date: string
  uploads: number
  questions: number
  failedFiles: number
  indexOperations: number
  evaluationRuns: number
}

export interface DashboardFileStatus {
  status: FileStatus
  value: number
}

export interface DashboardRecentFile {
  id: string
  knowledgeBaseId: string
  knowledgeBaseName: string
  fileName: string
  fileType: string
  status: FileStatus
  chunkCount: number
  updatedAt: string
}

export interface DashboardRecentSession {
  id: string
  knowledgeBaseId: string
  knowledgeBaseName: string
  title: string
  preview: string
  messageCount: number
  updatedAt: string
}

export interface DashboardRecentJob {
  id: string
  knowledgeBaseId: string | null
  knowledgeBaseName: string
  jobType: string
  status: DurableJobStatus
  stage: string | null
  progress: number
  errorMessage: string | null
  createdAt: string
  finishedAt: string | null
}

export interface DashboardRuntimeStatus {
  chatConfigured: boolean
  missingChatConfiguration: string[]
  embeddingKeyConfigured: boolean
}

export interface DashboardSnapshot {
  generatedAt: string
  timeZone: 'UTC'
  windowDays: number
  knowledgeBaseId: string | null
  metrics: DashboardMetric[]
  trend: DashboardTrendPoint[]
  fileStatuses: DashboardFileStatus[]
  recentFiles: DashboardRecentFile[]
  recentSessions: DashboardRecentSession[]
  recentIndexJobs: DashboardRecentJob[]
  recentEvaluations: DashboardRecentJob[]
  runtime: DashboardRuntimeStatus
  sectionErrors: Record<string, string>
}

export interface EvaluationQuestionResult {
  id: string
  question: string
  expectedAnswer: string
  modelAnswer: string
  matchedSources: number
  retrievalScore: number
  citationValid: boolean
  durationMs: number
  status: 'PASS' | 'REVIEW' | 'FAIL'
}

export interface EvaluationTask {
  id: string
  name: string
  knowledgeBaseId: string
  datasetName: string
  questionCount: number
  averageScore: number | null
  status: EvaluationStatus
  progress: number
  createdAt: string
  completedAt: string | null
  results: EvaluationQuestionResult[]
}

export interface EvaluationInput {
  name: string
  knowledgeBaseId: string
  datasetName: string
}

export interface EvaluationMetrics {
  datasetCount: number
  evaluatedQuestions: number
  averageRetrievalScore: number
  citationCoverage: number
  averageDurationMs: number
}

export type EvaluationMode = 'retrieval' | 'rag'

export interface EvaluationDataset {
  id: string
  ownerId: string
  name: string
  description: string
  originalFilename: string
  sha256: string
  sizeBytes: number
  caseCount: number
  createdAt: string
  updatedAt: string
}

export interface EvaluationSummary {
  runCount: number
  datasetCount: number
  statusCounts: Record<string, number>
}

export interface EvaluationRun {
  id: string
  name: string
  mode: EvaluationMode
  knowledgeBaseId: string
  knowledgeBaseName: string
  dataset: EvaluationDataset | null
  status: DurableJobStatus
  progress: number
  stage: string | null
  outcome: 'SUCCESS' | 'PARTIAL_SUCCESS' | null
  metrics: Record<string, unknown> | null
  errorCode: string | null
  errorMessage: string | null
  createdAt: string
  finishedAt: string | null
}

export interface EvaluationCase {
  index: number
  question: string
  expectedAnswers: string[]
  answer: string | null
  sources: Array<Record<string, unknown>>
  error: { type: string; message: string } | null
  retrievalMetrics: Record<string, unknown>
  citationMetrics: Record<string, unknown>
  answerMetrics: Record<string, unknown>
  timingSeconds: Record<string, number>
}

export interface EvaluationRunInput {
  datasetId: string
  knowledgeBaseId: string
  name: string
  mode: EvaluationMode
  topK: number
  scoreThreshold: number | null
  maxCalls: number
  maxGenerationTokens: number
  maxRuntimeSeconds: number
}

export interface AppSettings {
  chatModel: string | null
  embeddingProvider: string
  embeddingModel: string
  embeddingDimension: number
  vectorMetric: string
  apiKeyConfigured: boolean
  topK: number
  scoreThreshold: number | null
  maxContextCharacters: number
  webSearchEnabled: boolean
  defaultRetrievalMode: RetrievalMode
  minimumEvidenceCount: number
  freshnessTerms: string[]
  webSearchProvider: string
  webSearchProviderConfigured: boolean
  webSearchAllowedForCurrentUser: boolean
  source: 'environment' | 'persistent' | 'mock'
  updatedAt: string | null
}

export interface AppSettingsInput {
  chatModel: string | null
  topK: number
  scoreThreshold: number | null
  maxContextCharacters: number
  webSearchEnabled: boolean
  defaultRetrievalMode: RetrievalMode
  minimumEvidenceCount: number
  freshnessTerms: string[]
}
