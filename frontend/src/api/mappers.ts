import {
  AppError,
  type AppSettings,
  type AnswerFeedback,
  type ChatMessage,
  type ChatSession,
  type DashboardMetric,
  type DashboardRecentJob,
  type DashboardSnapshot,
  type FileRecord,
  type FileStatus,
  type DurableJob,
  type EvaluationCase,
  type EvaluationDataset,
  type EvaluationRun,
  type EvaluationSummary,
  type IndexCollection,
  type IndexState,
  type KnowledgeBase,
  type RetrievalResponse,
  type RetrievalAudit,
  type RetrievalMode,
  type SourceReference,
  type WebSearchStatus,
} from '@/types'

export interface ApiEnvelope {
  code: number
  message: string
  data: unknown
}

export type JobSnapshot = DurableJob

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function contractError(field: string): never {
  throw new AppError(
    'API_CONTRACT_INVALID',
    '后端响应与前端契约不一致。',
    `字段 ${field} 缺失或类型无效。`,
    { kind: 'parse' },
  )
}

function record(value: unknown, field: string): Record<string, unknown> {
  return isRecord(value) ? value : contractError(field)
}

function stringField(value: Record<string, unknown>, field: string): string {
  const candidate = value[field]
  return typeof candidate === 'string' ? candidate : contractError(field)
}

function nullableStringField(
  value: Record<string, unknown>,
  field: string,
): string | null {
  const candidate = value[field]
  return candidate === null || typeof candidate === 'string'
    ? candidate
    : contractError(field)
}

function optionalNullableStringField(
  value: Record<string, unknown>,
  field: string,
): string | null {
  return value[field] === undefined ? null : nullableStringField(value, field)
}

function numberField(value: Record<string, unknown>, field: string): number {
  const candidate = value[field]
  return typeof candidate === 'number' && Number.isFinite(candidate)
    ? candidate
    : contractError(field)
}

function booleanField(value: Record<string, unknown>, field: string): boolean {
  const candidate = value[field]
  return typeof candidate === 'boolean' ? candidate : contractError(field)
}

function nullableNumberField(
  value: Record<string, unknown>,
  field: string,
): number | null {
  const candidate = value[field]
  return candidate === null ||
    (typeof candidate === 'number' && Number.isFinite(candidate))
    ? candidate
    : contractError(field)
}

function isoDateField(value: Record<string, unknown>, field: string): string {
  const candidate = stringField(value, field)
  if (
    !/(?:Z|[+-]\d{2}:\d{2})$/u.test(candidate) ||
    Number.isNaN(Date.parse(candidate))
  ) {
    contractError(field)
  }
  return candidate
}

function nullableIsoDateField(
  value: Record<string, unknown>,
  field: string,
): string | null {
  const candidate = nullableStringField(value, field)
  if (candidate !== null && Number.isNaN(Date.parse(candidate))) {
    contractError(field)
  }
  return candidate
}

function retrievalModeField(
  value: Record<string, unknown>,
  field: string,
): RetrievalMode {
  const candidate = stringField(value, field)
  if (!['knowledge_only', 'knowledge_first', 'hybrid'].includes(candidate)) {
    contractError(field)
  }
  return candidate as RetrievalMode
}

function webSearchStatusField(
  value: Record<string, unknown>,
  field: string,
): WebSearchStatus {
  const candidate = stringField(value, field)
  if (
    ![
      'not_requested',
      'blocked_by_policy',
      'not_configured',
      'success',
      'partial',
      'failed',
      'timeout',
      'rate_limited',
      'query_rejected',
    ].includes(candidate)
  ) {
    contractError(field)
  }
  return candidate as WebSearchStatus
}

export function mapRetrievalAuditDto(value: unknown): RetrievalAudit {
  const dto = record(value, 'retrieval_audit')
  return {
    requestedMode: retrievalModeField(dto, 'requested_mode'),
    effectiveMode: retrievalModeField(dto, 'effective_mode'),
    webSearchTriggered: booleanField(dto, 'web_search_triggered'),
    webSearchStatus: webSearchStatusField(dto, 'web_search_status'),
    webTriggerReason: nullableStringField(dto, 'web_trigger_reason'),
    knowledgeSourceCount: numberField(dto, 'knowledge_source_count'),
    webSourceCount: numberField(dto, 'web_source_count'),
    fallbackReason: nullableStringField(dto, 'fallback_reason'),
  }
}

export function unwrapApiEnvelope(value: unknown): unknown {
  const envelope = record(value, 'response')
  const code = numberField(envelope, 'code')
  stringField(envelope, 'message')
  if (code !== 0) {
    throw new AppError(String(code), '后端返回了失败响应。', null, {
      kind: 'http',
      details: envelope.data,
    })
  }
  if (!Object.hasOwn(envelope, 'data')) contractError('data')
  return envelope.data
}

function dashboardStatus(value: unknown, field: string): FileStatus {
  if (
    typeof value !== 'string' ||
    !['PENDING', 'PROCESSING', 'SUCCESS', 'FAILED'].includes(value)
  ) {
    contractError(field)
  }
  return value as FileStatus
}

function mapDashboardJobDto(value: unknown): DashboardRecentJob {
  const dto = record(value, 'dashboard_job')
  const status = stringField(dto, 'status')
  if (
    ![
      'QUEUED',
      'RUNNING',
      'CANCEL_REQUESTED',
      'SUCCEEDED',
      'FAILED',
      'CANCELLED',
    ].includes(status)
  ) {
    contractError('dashboard_job.status')
  }
  const finishedAt = nullableStringField(dto, 'finished_at')
  if (finishedAt !== null) isoDateField({ finished_at: finishedAt }, 'finished_at')
  return {
    id: stringField(dto, 'id'),
    knowledgeBaseId: nullableStringField(dto, 'knowledge_base_id'),
    knowledgeBaseName: stringField(dto, 'knowledge_base_name'),
    jobType: stringField(dto, 'job_type'),
    status: status as DashboardRecentJob['status'],
    stage: nullableStringField(dto, 'stage'),
    progress: numberField(dto, 'progress'),
    errorMessage: nullableStringField(dto, 'error_message'),
    createdAt: isoDateField(dto, 'created_at'),
    finishedAt,
  }
}

export function mapDashboardDto(value: unknown): DashboardSnapshot {
  const dto = record(value, 'dashboard')
  const metricsDto = record(dto.metrics, 'dashboard.metrics')
  const filesTotal = numberField(metricsDto, 'files_total')
  const filesSuccess = numberField(metricsDto, 'files_success')
  const filesInProgress = numberField(metricsDto, 'files_in_progress')
  const filesFailed = numberField(metricsDto, 'files_failed')
  const userQuestions = numberField(metricsDto, 'user_questions')
  const assistantAnswers = numberField(metricsDto, 'assistant_answers')
  const buildingIndexes = numberField(metricsDto, 'building_indexes')
  const metrics: DashboardMetric[] = [
    {
      id: 'knowledgeBases',
      label: '知识库数量',
      value: numberField(metricsDto, 'knowledge_bases'),
      note: '当前可见范围',
    },
    {
      id: 'files',
      label: '文件总数',
      value: filesTotal,
      note: `成功 ${filesSuccess} · 待处理 ${filesInProgress} · 失败 ${filesFailed}`,
    },
    {
      id: 'chunks',
      label: '有效分块数量',
      value: numberField(metricsDto, 'chunks'),
      note: '来自文件持久化记录',
    },
    {
      id: 'questions',
      label: '用户问题',
      value: userQuestions,
      note: `完整助手回答 ${assistantAnswers}`,
    },
    {
      id: 'sessions',
      label: '会话数量',
      value: numberField(metricsDto, 'sessions'),
      note: '真实持久化会话',
    },
    {
      id: 'activeIndexes',
      label: '活动索引',
      value: numberField(metricsDto, 'active_indexes'),
      note: `构建中 ${buildingIndexes}`,
    },
  ]

  if (!Array.isArray(dto.trend)) contractError('dashboard.trend')
  const trend = dto.trend.map((raw) => {
    const item = record(raw, 'dashboard.trend.item')
    const day = stringField(item, 'date')
    if (!/^\d{4}-\d{2}-\d{2}$/u.test(day)) contractError('dashboard.trend.date')
    return {
      date: day,
      uploads: numberField(item, 'uploads'),
      questions: numberField(item, 'questions'),
      failedFiles: numberField(item, 'failed_files'),
      indexOperations: numberField(item, 'index_operations'),
      evaluationRuns: numberField(item, 'evaluation_runs'),
    }
  })
  if (!Array.isArray(dto.file_statuses)) contractError('dashboard.file_statuses')
  const fileStatuses = dto.file_statuses.map((raw) => {
    const item = record(raw, 'dashboard.file_statuses.item')
    return {
      status: dashboardStatus(item.status, 'dashboard.file_statuses.status'),
      value: numberField(item, 'count'),
    }
  })
  if (!Array.isArray(dto.recent_files)) contractError('dashboard.recent_files')
  const recentFiles = dto.recent_files.map((raw) => {
    const item = record(raw, 'dashboard.recent_files.item')
    return {
      id: stringField(item, 'id'),
      knowledgeBaseId: stringField(item, 'knowledge_base_id'),
      knowledgeBaseName: stringField(item, 'knowledge_base_name'),
      fileName: stringField(item, 'file_name'),
      fileType: stringField(item, 'file_type'),
      status: dashboardStatus(item.status, 'dashboard.recent_files.status'),
      chunkCount: numberField(item, 'chunk_count'),
      updatedAt: isoDateField(item, 'updated_at'),
    }
  })
  if (!Array.isArray(dto.recent_sessions)) {
    contractError('dashboard.recent_sessions')
  }
  const recentSessions = dto.recent_sessions.map((raw) => {
    const item = record(raw, 'dashboard.recent_sessions.item')
    return {
      id: stringField(item, 'id'),
      knowledgeBaseId: stringField(item, 'knowledge_base_id'),
      knowledgeBaseName: stringField(item, 'knowledge_base_name'),
      title: stringField(item, 'title'),
      preview: stringField(item, 'preview'),
      messageCount: numberField(item, 'message_count'),
      updatedAt: isoDateField(item, 'updated_at'),
    }
  })
  if (!Array.isArray(dto.recent_index_jobs)) {
    contractError('dashboard.recent_index_jobs')
  }
  if (!Array.isArray(dto.recent_evaluations)) {
    contractError('dashboard.recent_evaluations')
  }
  const runtime = record(dto.runtime, 'dashboard.runtime')
  const sectionErrorsDto = record(dto.section_errors, 'dashboard.section_errors')
  const sectionErrors: Record<string, string> = {}
  for (const [key, raw] of Object.entries(sectionErrorsDto)) {
    if (typeof raw !== 'string') contractError(`dashboard.section_errors.${key}`)
    sectionErrors[key] = raw
  }
  const missing = runtime.missing_chat_configuration
  if (!Array.isArray(missing) || !missing.every((item) => typeof item === 'string')) {
    contractError('dashboard.runtime.missing_chat_configuration')
  }
  const timeZone = stringField(dto, 'time_zone')
  if (timeZone !== 'UTC') contractError('dashboard.time_zone')
  return {
    generatedAt: isoDateField(dto, 'generated_at'),
    timeZone,
    windowDays: numberField(dto, 'window_days'),
    knowledgeBaseId: nullableStringField(dto, 'knowledge_base_id'),
    metrics,
    trend,
    fileStatuses,
    recentFiles,
    recentSessions,
    recentIndexJobs: dto.recent_index_jobs.map(mapDashboardJobDto),
    recentEvaluations: dto.recent_evaluations.map(mapDashboardJobDto),
    runtime: {
      chatConfigured: booleanField(runtime, 'chat_configured'),
      missingChatConfiguration: [...missing],
      embeddingKeyConfigured: booleanField(runtime, 'embedding_key_configured'),
    },
    sectionErrors,
  }
}

export function mapKnowledgeBaseDto(value: unknown): KnowledgeBase {
  const dto = record(value, 'knowledge_base')
  const status = stringField(dto, 'status')
  if (!['READY', 'BUILDING', 'FAILED', 'EMPTY'].includes(status)) {
    contractError('status')
  }
  const webAccessPolicy = stringField(dto, 'web_access_policy')
  if (!['inherit', 'allow', 'deny'].includes(webAccessPolicy)) {
    contractError('web_access_policy')
  }
  return {
    id: stringField(dto, 'id'),
    name: stringField(dto, 'name'),
    description: nullableStringField(dto, 'description') ?? '',
    fileCount: numberField(dto, 'file_count'),
    chunkCount: numberField(dto, 'chunk_count'),
    embeddingModel: stringField(dto, 'embedding_model'),
    updatedAt: isoDateField(dto, 'updated_at'),
    status: status as KnowledgeBase['status'],
    webAccessPolicy: webAccessPolicy as KnowledgeBase['webAccessPolicy'],
  }
}

export function mapFileDto(value: unknown): FileRecord {
  const dto = record(value, 'file')
  const status = stringField(dto, 'status')
  if (!['PENDING', 'PROCESSING', 'SUCCESS', 'FAILED'].includes(status)) {
    contractError('status')
  }
  const lastIndexed = nullableStringField(dto, 'last_successful_indexed_at')
  if (lastIndexed !== null && Number.isNaN(Date.parse(lastIndexed))) {
    contractError('last_successful_indexed_at')
  }
  const fileType = stringField(dto, 'file_type').replace(/^\./u, '').toUpperCase()
  return {
    id: stringField(dto, 'id'),
    knowledgeBaseId: stringField(dto, 'knowledge_base_id'),
    fileName: stringField(dto, 'original_name'),
    fileType,
    fileSize: numberField(dto, 'file_size'),
    status: status as FileStatus,
    progress: numberField(dto, 'progress'),
    chunkCount: numberField(dto, 'chunk_count'),
    hasActiveVectors: booleanField(dto, 'has_active_vectors'),
    activeIndexConfigHash: nullableStringField(dto, 'active_index_config_hash'),
    lastSuccessfulIndexedAt: lastIndexed,
    errorMessage: nullableStringField(dto, 'error_message'),
    createdAt: isoDateField(dto, 'created_at'),
    updatedAt: isoDateField(dto, 'updated_at'),
    filePath: stringField(dto, 'file_path'),
    contentHash: `md5:${stringField(dto, 'md5')}`,
    embeddingProvider: stringField(dto, 'embedding_provider'),
    embeddingModel: stringField(dto, 'embedding_model'),
    embeddingDimension: numberField(dto, 'embedding_dimension'),
    vectorMetric: stringField(dto, 'vector_metric'),
    collectionName: nullableStringField(dto, 'collection_name'),
    processingDuration: null,
  }
}

export function mapJobDto(value: unknown): JobSnapshot {
  const dto = record(value, 'job')
  const status = stringField(dto, 'status')
  if (
    ![
      'QUEUED',
      'RUNNING',
      'CANCEL_REQUESTED',
      'SUCCEEDED',
      'FAILED',
      'CANCELLED',
    ].includes(status)
  ) {
    contractError('job.status')
  }
  return {
    id: stringField(dto, 'id'),
    jobType: typeof dto.job_type === 'string' ? dto.job_type : '',
    status: status as JobSnapshot['status'],
    progress: numberField(dto, 'progress'),
    errorMessage: nullableStringField(dto, 'error_message'),
    stage: optionalNullableStringField(dto, 'stage'),
    errorCode: optionalNullableStringField(dto, 'error_code'),
    createdAt:
      typeof dto.created_at === 'string' ? isoDateField(dto, 'created_at') : '',
    updatedAt:
      typeof dto.updated_at === 'string' ? isoDateField(dto, 'updated_at') : '',
    finishedAt:
      dto.finished_at === undefined ? null : nullableIsoDateField(dto, 'finished_at'),
    resourceId: optionalNullableStringField(dto, 'resource_id'),
    resourceName: optionalNullableStringField(dto, 'resource_name_snapshot'),
  }
}

export function mapIndexStateDto(value: unknown): IndexState {
  const dto = record(value, 'index_state')
  const knowledgeBaseId = stringField(dto, 'knowledge_base_id')
  const startedAt = nullableIsoDateField(dto, 'building_started_at')
  const rawCollections = dto.collections
  if (!Array.isArray(rawCollections)) contractError('collections')
  const collections = rawCollections.map((raw): IndexCollection => {
    const item = record(raw, 'index_collection')
    const lifecycle = stringField(item, 'role')
    if (!['active', 'previous', 'building', 'cleanup', 'orphan'].includes(lifecycle)) {
      contractError('index_collection.role')
    }
    const provider = nullableStringField(item, 'embedding_provider') ?? ''
    const model = nullableStringField(item, 'embedding_model') ?? ''
    const dimension =
      item.embedding_dimension === null ? 0 : numberField(item, 'embedding_dimension')
    const metric = nullableStringField(item, 'distance_metric') ?? ''
    const configHash = nullableStringField(item, 'embedding_config_hash') ?? ''
    return {
      id: stringField(item, 'collection_name'),
      collectionName: stringField(item, 'collection_name'),
      knowledgeBaseId,
      lifecycle: lifecycle as IndexCollection['lifecycle'],
      generation: nullableStringField(item, 'generation') ?? '—',
      fileCount: nullableNumberField(item, 'file_count') ?? 0,
      chunkCount: nullableNumberField(item, 'chunk_count') ?? 0,
      createdAt: lifecycle === 'building' && startedAt ? startedAt : '',
      config: {
        provider,
        model,
        dimension,
        normalization: false,
        metric,
        configHash,
      },
      exists: booleanField(item, 'exists'),
      safeToCleanup: booleanField(item, 'safe_to_cleanup'),
      cleanupReason: nullableStringField(item, 'cleanup_reason'),
      error: nullableStringField(item, 'error'),
    }
  })
  return {
    knowledgeBaseId,
    knowledgeBaseName: stringField(dto, 'knowledge_base_name'),
    rebuildStatus: stringField(dto, 'rebuild_status'),
    rebuildRunId: nullableStringField(dto, 'rebuild_run_id'),
    buildingStartedAt: startedAt,
    collections,
    latestJob: dto.latest_job === null ? null : mapJobDto(dto.latest_job),
  }
}

export function mapEvaluationDatasetDto(value: unknown): EvaluationDataset {
  const dto = record(value, 'evaluation_dataset')
  return {
    id: stringField(dto, 'id'),
    ownerId: stringField(dto, 'owner_id'),
    name: stringField(dto, 'name'),
    description: nullableStringField(dto, 'description') ?? '',
    originalFilename: stringField(dto, 'original_filename'),
    sha256: stringField(dto, 'sha256'),
    sizeBytes: numberField(dto, 'size_bytes'),
    caseCount: numberField(dto, 'case_count'),
    createdAt: isoDateField(dto, 'created_at'),
    updatedAt: isoDateField(dto, 'updated_at'),
  }
}

export function mapEvaluationSummaryDto(value: unknown): EvaluationSummary {
  const dto = record(value, 'evaluation_summary')
  const counts = record(dto.status_counts, 'status_counts')
  const statusCounts: Record<string, number> = {}
  for (const [key, raw] of Object.entries(counts)) {
    if (typeof raw !== 'number' || !Number.isFinite(raw)) {
      contractError(`status_counts.${key}`)
    }
    statusCounts[key] = raw
  }
  return {
    runCount: numberField(dto, 'run_count'),
    datasetCount: numberField(dto, 'dataset_count'),
    statusCounts,
  }
}

export function mapEvaluationRunDto(value: unknown): EvaluationRun {
  const dto = record(value, 'evaluation_run')
  const jobDto = record(dto.job, 'evaluation_run.job')
  const job = mapJobDto(jobDto)
  const mode = stringField(dto, 'mode')
  if (!['retrieval', 'rag'].includes(mode)) contractError('mode')
  const resolvedMode: EvaluationRun['mode'] = mode === 'retrieval' ? 'retrieval' : 'rag'
  const outcome = nullableStringField(dto, 'outcome')
  if (outcome !== null && !['SUCCESS', 'PARTIAL_SUCCESS'].includes(outcome)) {
    contractError('outcome')
  }
  const resolvedOutcome: EvaluationRun['outcome'] =
    outcome === 'SUCCESS' || outcome === 'PARTIAL_SUCCESS' ? outcome : null
  const metrics = dto.metrics
  if (metrics !== null && !isRecord(metrics)) contractError('metrics')
  return {
    id: job.id,
    name: stringField(dto, 'run_name'),
    mode: resolvedMode,
    knowledgeBaseId: job.resourceId ?? '',
    knowledgeBaseName: job.resourceName ?? '已删除知识库',
    dataset: dto.dataset === null ? null : mapEvaluationDatasetDto(dto.dataset),
    status: job.status,
    progress: job.progress,
    stage: job.stage,
    outcome: resolvedOutcome,
    metrics,
    errorCode: job.errorCode,
    errorMessage: job.errorMessage,
    createdAt: job.createdAt,
    finishedAt: job.finishedAt,
  }
}

export function mapEvaluationCaseDto(value: unknown): EvaluationCase {
  const dto = record(value, 'evaluation_case')
  const expected = dto.expected_answer
  const sources = dto.sources
  if (!Array.isArray(expected) || !expected.every((item) => typeof item === 'string')) {
    contractError('expected_answer')
  }
  if (!Array.isArray(sources) || !sources.every(isRecord)) contractError('sources')
  const error = dto.error === null ? null : record(dto.error, 'error')
  return {
    index: numberField(dto, 'index'),
    question: stringField(dto, 'question'),
    expectedAnswers: expected,
    answer: nullableStringField(dto, 'answer'),
    sources,
    error:
      error === null
        ? null
        : { type: stringField(error, 'type'), message: stringField(error, 'message') },
    retrievalMetrics: record(dto.retrieval_metrics, 'retrieval_metrics'),
    citationMetrics: record(dto.citation_metrics, 'citation_metrics'),
    answerMetrics: record(dto.answer_metrics, 'answer_metrics'),
    timingSeconds: record(dto.timing_seconds, 'timing_seconds') as Record<
      string,
      number
    >,
  }
}

export function mapSettingsDto(value: unknown): AppSettings {
  const dto = record(value, 'settings')
  const source = stringField(dto, 'source')
  if (!['environment', 'persistent'].includes(source)) contractError('source')
  const updatedAt = nullableStringField(dto, 'updated_at')
  if (updatedAt !== null && Number.isNaN(Date.parse(updatedAt))) {
    contractError('updated_at')
  }
  return {
    chatModel: nullableStringField(dto, 'chat_model'),
    topK: numberField(dto, 'retrieval_top_k'),
    scoreThreshold: nullableNumberField(dto, 'retrieval_score_threshold'),
    maxContextCharacters: numberField(dto, 'rag_context_max_chars'),
    webSearchEnabled: booleanField(dto, 'web_search_enabled'),
    defaultRetrievalMode: retrievalModeField(dto, 'default_retrieval_mode'),
    minimumEvidenceCount: numberField(dto, 'retrieval_min_evidence_count'),
    freshnessTerms: (() => {
      const terms = dto.retrieval_freshness_terms
      if (!Array.isArray(terms) || !terms.every((term) => typeof term === 'string')) {
        return contractError('retrieval_freshness_terms')
      }
      return terms
    })(),
    webSearchProvider: stringField(dto, 'web_search_provider'),
    webSearchProviderConfigured: booleanField(dto, 'web_search_provider_configured'),
    webSearchAllowedForCurrentUser: booleanField(
      dto,
      'web_search_allowed_for_current_user',
    ),
    embeddingProvider: stringField(dto, 'embedding_provider'),
    embeddingModel: stringField(dto, 'embedding_model'),
    embeddingDimension: numberField(dto, 'embedding_dimension'),
    vectorMetric: stringField(dto, 'vector_metric'),
    apiKeyConfigured: booleanField(dto, 'dashscope_api_key_configured'),
    source: source as AppSettings['source'],
    updatedAt,
  }
}

export function mapRetrievalDto(value: unknown): RetrievalResponse {
  const dto = record(value, 'retrieval')
  const rawResults = dto.results
  if (!Array.isArray(rawResults)) contractError('results')
  const results = rawResults.map((raw, index) => {
    const item = record(raw, `results[${index}]`)
    const metadata = record(item.metadata, `results[${index}].metadata`)
    return {
      rank: numberField(item, 'rank'),
      score: numberField(item, 'score'),
      fileId: stringField(item, 'file_id'),
      fileName: stringField(item, 'file_name'),
      chunkId: stringField(item, 'chunk_id'),
      content: stringField(item, 'content'),
      metadata: metadata as RetrievalResponse['results'][number]['metadata'],
    }
  })
  return {
    queryTimeMs: numberField(dto, 'query_time_ms'),
    resultCount: numberField(dto, 'result_count'),
    results,
  }
}

export function mapSourceReferenceDto(value: unknown): SourceReference {
  const dto = record(value, 'source_reference')
  const rawMetadata = record(dto.metadata, 'source_reference.metadata')
  const sourceType = stringField(dto, 'source_type')
  if (!['knowledge_base', 'web'].includes(sourceType)) {
    contractError('source_reference.source_type')
  }
  return {
    citationNumber: numberField(dto, 'citation_number'),
    sourceType: sourceType as SourceReference['sourceType'],
    reference: stringField(dto, 'reference'),
    title: stringField(dto, 'title'),
    fileId: nullableStringField(dto, 'file_id'),
    fileName: nullableStringField(dto, 'file_name'),
    chunkId: nullableStringField(dto, 'chunk_id'),
    url: nullableStringField(dto, 'url'),
    domain: nullableStringField(dto, 'domain'),
    publishedAt: nullableIsoDateField(dto, 'published_at'),
    accessedAt: nullableIsoDateField(dto, 'accessed_at'),
    contentPreview: stringField(dto, 'content_preview'),
    score: numberField(dto, 'score'),
    metadata: rawMetadata as SourceReference['metadata'],
  }
}

export function mapSessionDto(value: unknown): ChatSession {
  const dto = record(value, 'session')
  return {
    id: stringField(dto, 'id'),
    knowledgeBaseId: stringField(dto, 'knowledge_base_id'),
    title: stringField(dto, 'title'),
    preview: stringField(dto, 'preview'),
    createdAt: isoDateField(dto, 'created_at'),
    updatedAt: isoDateField(dto, 'updated_at'),
    messageCount: numberField(dto, 'message_count'),
  }
}

export function mapMessageDto(value: unknown): ChatMessage {
  const dto = record(value, 'message')
  const role = stringField(dto, 'role')
  const status = stringField(dto, 'status')
  if (!['user', 'assistant', 'system'].includes(role)) contractError('role')
  if (!['complete', 'streaming', 'failed', 'cancelled'].includes(status)) {
    contractError('status')
  }
  const feedback = nullableStringField(dto, 'feedback')
  if (feedback !== null && !['like', 'dislike'].includes(feedback)) {
    contractError('feedback')
  }
  const rawReferences = dto.references
  if (!Array.isArray(rawReferences)) contractError('references')
  const requestedMode =
    dto.requested_mode === null
      ? 'knowledge_only'
      : retrievalModeField(dto, 'requested_mode')
  const effectiveMode =
    dto.effective_mode === null
      ? 'knowledge_only'
      : retrievalModeField(dto, 'effective_mode')
  return {
    id: stringField(dto, 'id'),
    sessionId: stringField(dto, 'session_id'),
    role: role as ChatMessage['role'],
    content: stringField(dto, 'content'),
    createdAt: isoDateField(dto, 'created_at'),
    updatedAt: isoDateField(dto, 'updated_at'),
    status: status as ChatMessage['status'],
    sources: rawReferences.map(mapSourceReferenceDto),
    metrics: null,
    feedback: feedback as AnswerFeedback,
    errorCode: nullableStringField(dto, 'error_code'),
    errorMessage: nullableStringField(dto, 'error_message'),
    replyToMessageId: nullableStringField(dto, 'reply_to_message_id'),
    requestedMode,
    effectiveMode,
    webSearchTriggered: booleanField(dto, 'web_search_triggered'),
    webSearchStatus: webSearchStatusField(dto, 'web_search_status'),
    webTriggerReason: nullableStringField(dto, 'web_trigger_reason'),
    knowledgeSourceCount: numberField(dto, 'knowledge_source_count'),
    webSourceCount: numberField(dto, 'web_source_count'),
    fallbackReason: nullableStringField(dto, 'fallback_reason'),
  }
}

export function mapFeedbackDto(value: unknown): AnswerFeedback {
  const dto = record(value, 'feedback')
  const feedback = nullableStringField(dto, 'value')
  if (feedback !== null && !['like', 'dislike'].includes(feedback)) {
    contractError('feedback.value')
  }
  return feedback as AnswerFeedback
}
