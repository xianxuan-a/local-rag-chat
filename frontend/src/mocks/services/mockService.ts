import {
  BASE_TIME,
  dashboardTrendFixtures,
  defaultSettings,
  retrievalFixtures,
  sourceFixtures,
  webSourceFixture,
} from '@/mocks/fixtures'
import { delay } from '@/mocks/delay'
import {
  cloneValue,
  getMockDatabase,
  nextMockId,
  nextMockTimestamp,
} from '@/mocks/state'
import {
  AppError,
  type ChatMessage,
  type AppSettings,
  type AppSettingsInput,
  type ChatRequest,
  type ChatRetryRequest,
  type ChatStreamResult,
  type ChatSession,
  type DashboardSnapshot,
  type EvaluationInput,
  type EvaluationMetrics,
  type EvaluationTask,
  type FileRecord,
  type FileUploadInput,
  type IndexCollection,
  type KnowledgeBase,
  type KnowledgeBaseInput,
  type RebuildSnapshot,
  type RetrievalRequest,
  type RetrievalResponse,
  type RetrievalAudit,
} from '@/types'
import type {
  ChatStreamHandlers,
  ProgressHandlers,
  RequestOptions,
  RebuildHandlers,
} from '@/api/contracts'
import { isAbortError } from '@/utils/abort'

const rebuildSteps = [
  '准备数据',
  '解析文件',
  'Embedding',
  '写入 Chroma',
  '校验索引',
  '原子切换',
  '完成',
]

export async function getSettings(options?: RequestOptions): Promise<AppSettings> {
  await delay(180, options?.signal)
  return cloneValue(getMockDatabase().settings)
}

export async function updateSettings(input: AppSettingsInput): Promise<AppSettings> {
  await delay(240)
  const current = getMockDatabase().settings
  getMockDatabase().settings = {
    ...current,
    ...input,
    source: 'mock',
    updatedAt: nextMockTimestamp(),
  }
  return cloneValue(getMockDatabase().settings)
}

function requireKnowledgeBase(id: string): KnowledgeBase {
  const knowledgeBase = getMockDatabase().knowledgeBases.find((item) => item.id === id)
  if (knowledgeBase === undefined) {
    throw new AppError('KNOWLEDGE_BASE_NOT_FOUND', '知识库不存在或已被删除。')
  }
  return knowledgeBase
}

function requireFile(id: string): FileRecord {
  const file = getMockDatabase().files.find((item) => item.id === id)
  if (file === undefined) {
    throw new AppError('FILE_NOT_FOUND', '文件不存在或已被删除。')
  }
  return file
}

function requireIndex(id: string): IndexCollection {
  const collection = getMockDatabase().indexes.find((item) => item.id === id)
  if (collection === undefined) {
    throw new AppError('INDEX_NOT_FOUND', '索引 Collection 不存在。')
  }
  return collection
}

function recalculateKnowledgeBase(knowledgeBaseId: string): void {
  const database = getMockDatabase()
  const knowledgeBase = database.knowledgeBases.find(
    (item) => item.id === knowledgeBaseId,
  )
  if (knowledgeBase === undefined) return
  const files = database.files.filter(
    (item) => item.knowledgeBaseId === knowledgeBaseId,
  )
  knowledgeBase.fileCount = files.length
  knowledgeBase.chunkCount = files.reduce((total, item) => total + item.chunkCount, 0)
  if (files.length === 0) knowledgeBase.status = 'EMPTY'
  knowledgeBase.updatedAt = nextMockTimestamp()
}

function buildAssistantAnswer(noSources: boolean, includeWeb = false): string {
  if (noSources) {
    return '当前知识库中没有检索到达到阈值的有效来源。我不会根据低相关内容生成结论，你可以换一种问法或调整检索范围后重试。'
  }
  const answer = [
    '建议从一套可解释、便于评测的混合检索配置开始：',
    '\n\n1. **TopK 设为 5**，候选倍数设为 3。',
    '\n2. **score threshold 设为 0.72**，再根据评测结果微调。',
    '\n3. 开启内容哈希去重，保留 `file_id`、`chunk_id` 与 metadata。',
    '\n\n索引重建期间继续使用 active Collection，新版本校验后再原子切换。[K1]',
  ].join('')
  return includeWeb ? `${answer}\n\n公开参数补充见 [W1]。` : answer
}

function emptyMockAudit(): RetrievalAudit {
  return {
    requestedMode: 'knowledge_only',
    effectiveMode: 'knowledge_only',
    webSearchTriggered: false,
    webSearchStatus: 'not_requested',
    webTriggerReason: null,
    knowledgeSourceCount: 0,
    webSourceCount: 0,
    fallbackReason: null,
  }
}

function buildMockAudit(
  requestedMode: ChatRequest['mode'],
  question: string,
  knowledgeBase: KnowledgeBase,
  topK: number,
): RetrievalAudit {
  const settings = getMockDatabase().settings
  const noSources = /无引用|无来源|不存在|量子航海/.test(question)
  if (requestedMode === 'knowledge_only') {
    return {
      ...emptyMockAudit(),
      requestedMode,
      knowledgeSourceCount: noSources ? 0 : Math.min(topK, sourceFixtures.length),
    }
  }
  if (!settings.webSearchEnabled || knowledgeBase.webAccessPolicy === 'deny') {
    return {
      ...emptyMockAudit(),
      requestedMode,
      webSearchStatus: 'blocked_by_policy',
      knowledgeSourceCount: noSources ? 0 : Math.min(topK, sourceFixtures.length),
      fallbackReason: !settings.webSearchEnabled
        ? 'global_web_search_disabled'
        : 'knowledge_base_web_search_denied',
    }
  }
  const freshnessRequested = settings.freshnessTerms.some((term) =>
    question.toLocaleLowerCase().includes(term.toLocaleLowerCase()),
  )
  const useWeb = requestedMode === 'hybrid' || freshnessRequested || noSources
  return {
    requestedMode,
    effectiveMode: requestedMode,
    webSearchTriggered: useWeb,
    webSearchStatus: noSources ? 'failed' : useWeb ? 'success' : 'not_requested',
    webTriggerReason:
      requestedMode === 'hybrid'
        ? 'hybrid_requested'
        : freshnessRequested
          ? 'freshness_required'
          : noSources
            ? 'no_results'
            : null,
    knowledgeSourceCount: noSources ? 0 : Math.min(topK, sourceFixtures.length),
    webSourceCount: noSources || !useWeb ? 0 : 1,
    fallbackReason: noSources ? 'web_no_usable_sources' : null,
  }
}

function mockSourcesForAudit(
  audit: RetrievalAudit,
  topK: number,
): ChatMessage['sources'] {
  const local = sourceFixtures.slice(0, Math.min(topK, audit.knowledgeSourceCount))
  return audit.webSourceCount > 0 ? [...local, webSourceFixture] : local
}

export async function getDashboard(
  options: {
    knowledgeBaseId?: string
    windowDays?: number
    recentLimit?: number
    signal?: AbortSignal
  } = {},
): Promise<DashboardSnapshot> {
  await delay(320, options.signal)
  const database = getMockDatabase()
  const knowledgeBases = options.knowledgeBaseId
    ? database.knowledgeBases.filter((item) => item.id === options.knowledgeBaseId)
    : database.knowledgeBases
  const visibleIds = new Set(knowledgeBases.map((item) => item.id))
  const files = database.files.filter((item) => visibleIds.has(item.knowledgeBaseId))
  const sessions = database.sessions.filter((item) =>
    visibleIds.has(item.knowledgeBaseId),
  )
  const messages = sessions.flatMap((session) => database.messages[session.id] ?? [])
  const indexes = database.indexes.filter((item) =>
    visibleIds.has(item.knowledgeBaseId),
  )
  const recentLimit = options.recentLimit ?? 5
  const fileStatusValue = (status: FileRecord['status']): number =>
    files.filter((item) => item.status === status).length
  const metrics: DashboardSnapshot['metrics'] = [
    {
      id: 'knowledgeBases',
      label: '知识库数量',
      value: knowledgeBases.length,
      note: '显式 Mock 数据',
    },
    {
      id: 'files',
      label: '文件总数',
      value: files.length,
      note: `成功 ${fileStatusValue('SUCCESS')} · 待处理 ${
        fileStatusValue('PENDING') + fileStatusValue('PROCESSING')
      } · 失败 ${fileStatusValue('FAILED')}`,
    },
    {
      id: 'chunks',
      label: '有效分块数量',
      value: files.reduce((total, item) => total + item.chunkCount, 0),
      note: '显式 Mock 数据',
    },
    {
      id: 'questions',
      label: '用户问题',
      value: messages.filter(
        (item) => item.role === 'user' && item.status === 'complete',
      ).length,
      note: `完整助手回答 ${
        messages.filter(
          (item) => item.role === 'assistant' && item.status === 'complete',
        ).length
      }`,
    },
    {
      id: 'sessions',
      label: '会话数量',
      value: sessions.length,
      note: '显式 Mock 数据',
    },
    {
      id: 'activeIndexes',
      label: '活动索引',
      value: indexes.filter((item) => item.lifecycle === 'active').length,
      note: `构建中 ${indexes.filter((item) => item.lifecycle === 'building').length}`,
    },
  ]
  return cloneValue({
    generatedAt: BASE_TIME,
    timeZone: 'UTC',
    windowDays: options.windowDays ?? 7,
    knowledgeBaseId: options.knowledgeBaseId ?? null,
    metrics,
    trend: dashboardTrendFixtures.slice(-(options.windowDays ?? 7)),
    fileStatuses: (['SUCCESS', 'PROCESSING', 'PENDING', 'FAILED'] as const).map(
      (status) => ({ status, value: fileStatusValue(status) }),
    ),
    recentFiles: files.slice(0, recentLimit).map((item) => ({
      id: item.id,
      knowledgeBaseId: item.knowledgeBaseId,
      knowledgeBaseName:
        knowledgeBases.find((candidate) => candidate.id === item.knowledgeBaseId)
          ?.name ?? 'Mock 知识库',
      fileName: item.fileName,
      fileType: item.fileType,
      status: item.status,
      chunkCount: item.chunkCount,
      updatedAt: item.updatedAt,
    })),
    recentSessions: sessions.slice(0, recentLimit).map((item) => ({
      id: item.id,
      knowledgeBaseId: item.knowledgeBaseId,
      knowledgeBaseName:
        knowledgeBases.find((candidate) => candidate.id === item.knowledgeBaseId)
          ?.name ?? 'Mock 知识库',
      title: item.title,
      preview: item.preview,
      messageCount: item.messageCount,
      updatedAt: item.updatedAt,
    })),
    recentIndexJobs: [],
    recentEvaluations: [],
    runtime: {
      chatConfigured: true,
      missingChatConfiguration: [],
      embeddingKeyConfigured: true,
    },
    sectionErrors: {},
  })
}

export async function listKnowledgeBases(
  options?: RequestOptions,
): Promise<KnowledgeBase[]> {
  await delay(260, options?.signal)
  return cloneValue(getMockDatabase().knowledgeBases)
}

export async function getKnowledgeBase(
  id: string,
  options?: RequestOptions,
): Promise<KnowledgeBase> {
  await delay(180, options?.signal)
  return cloneValue(requireKnowledgeBase(id))
}

export async function createKnowledgeBase(
  input: KnowledgeBaseInput,
): Promise<KnowledgeBase> {
  await delay(520)
  if (input.name.trim().length < 2) {
    throw new AppError('VALIDATION_ERROR', '知识库名称至少需要 2 个字符。')
  }
  if (input.name.includes('失败')) {
    throw new AppError(
      'CREATE_FAILED',
      '知识库创建失败。',
      'Mock service rejected this deterministic failure case.',
    )
  }
  const database = getMockDatabase()
  if (
    database.knowledgeBases.some(
      (item) => item.name.toLowerCase() === input.name.trim().toLowerCase(),
    )
  ) {
    throw new AppError('DUPLICATE_NAME', '已存在同名知识库。')
  }
  const knowledgeBase: KnowledgeBase = {
    id: nextMockId('kb'),
    name: input.name.trim(),
    description: input.description.trim(),
    fileCount: 0,
    chunkCount: 0,
    embeddingModel: defaultSettings.embeddingModel,
    updatedAt: nextMockTimestamp(),
    status: 'EMPTY',
    webAccessPolicy: input.webAccessPolicy,
  }
  database.knowledgeBases.unshift(knowledgeBase)
  return cloneValue(knowledgeBase)
}

export async function updateKnowledgeBase(
  id: string,
  input: KnowledgeBaseInput,
): Promise<KnowledgeBase> {
  await delay(420)
  const knowledgeBase = requireKnowledgeBase(id)
  knowledgeBase.name = input.name.trim()
  knowledgeBase.description = input.description.trim()
  knowledgeBase.webAccessPolicy = input.webAccessPolicy
  knowledgeBase.updatedAt = nextMockTimestamp()
  return cloneValue(knowledgeBase)
}

export async function deleteKnowledgeBase(id: string): Promise<void> {
  await delay(420)
  const database = getMockDatabase()
  requireKnowledgeBase(id)
  database.knowledgeBases = database.knowledgeBases.filter((item) => item.id !== id)
  database.files = database.files.filter((item) => item.knowledgeBaseId !== id)
  database.indexes = database.indexes.filter((item) => item.knowledgeBaseId !== id)
  const removedSessionIds = database.sessions
    .filter((item) => item.knowledgeBaseId === id)
    .map((item) => item.id)
  database.sessions = database.sessions.filter((item) => item.knowledgeBaseId !== id)
  for (const sessionId of removedSessionIds) delete database.messages[sessionId]
}

export async function listFiles(
  knowledgeBaseId: string,
  options?: RequestOptions,
): Promise<FileRecord[]> {
  await delay(280, options?.signal)
  requireKnowledgeBase(knowledgeBaseId)
  return cloneValue(
    getMockDatabase().files.filter((item) => item.knowledgeBaseId === knowledgeBaseId),
  )
}

export async function getFile(id: string): Promise<FileRecord> {
  await delay(180)
  return cloneValue(requireFile(id))
}

export async function addFile(
  knowledgeBaseId: string,
  input: FileUploadInput,
): Promise<FileRecord> {
  await delay(460)
  requireKnowledgeBase(knowledgeBaseId)
  const timestamp = nextMockTimestamp()
  const extension = input.file.name.split('.').pop()?.toUpperCase() ?? 'FILE'
  const file: FileRecord = {
    id: nextMockId('file'),
    knowledgeBaseId,
    fileName: input.file.name,
    fileType: extension,
    fileSize: input.file.size,
    status: 'PENDING',
    progress: 0,
    chunkCount: 0,
    hasActiveVectors: false,
    activeIndexConfigHash: null,
    lastSuccessfulIndexedAt: null,
    errorMessage: null,
    createdAt: timestamp,
    updatedAt: timestamp,
    filePath: `/mock/uploads/${input.file.name}`,
    contentHash: `sha256:${nextMockId('hash').replaceAll('-', '')}`,
    embeddingProvider: 'DashScope',
    embeddingModel: 'text-embedding-v4',
    embeddingDimension: 1024,
    vectorMetric: 'cosine',
    collectionName: null,
    processingDuration: null,
  }
  getMockDatabase().files.unshift(file)
  recalculateKnowledgeBase(knowledgeBaseId)
  return cloneValue(file)
}

export async function processFile(
  id: string,
  handlers: ProgressHandlers,
): Promise<FileRecord> {
  const file = requireFile(id)
  if (file.status === 'PROCESSING') {
    throw new AppError('FILE_BUSY', '文件正在处理中，请稍候。')
  }
  file.status = 'PROCESSING'
  file.errorMessage = null
  file.progress = 4
  handlers.onProgress(file.progress)

  const startedAt = 1_000
  try {
    for (const progress of [18, 38, 62, 84, 100]) {
      await delay(320, handlers.signal)
      file.progress = progress
      file.updatedAt = nextMockTimestamp()
      handlers.onProgress(progress)
      if (file.fileName.includes('损坏') && progress >= 38) {
        file.status = 'FAILED'
        file.progress = 0
        file.chunkCount = 0
        file.errorMessage = 'PDF parsing failed: invalid xref table'
        file.processingDuration = 1_120
        throw new AppError(
          'FILE_PROCESSING_FAILED',
          '文件处理失败。',
          file.errorMessage,
        )
      }
    }
  } catch (error) {
    if (isAbortError(error)) {
      file.status = 'PENDING'
      file.progress = 0
      file.updatedAt = nextMockTimestamp()
    }
    throw error
  }

  file.status = 'SUCCESS'
  file.chunkCount = Math.max(24, Math.round(file.fileSize / 18_000))
  file.hasActiveVectors = true
  file.activeIndexConfigHash = 'a45d8b661c2'
  file.lastSuccessfulIndexedAt = nextMockTimestamp()
  file.collectionName = 'kb_product_active_g12'
  file.processingDuration = startedAt + file.chunkCount * 22
  file.updatedAt = nextMockTimestamp()
  recalculateKnowledgeBase(file.knowledgeBaseId)
  return cloneValue(file)
}

export async function deleteFile(id: string): Promise<void> {
  await delay(360)
  const file = requireFile(id)
  const database = getMockDatabase()
  database.files = database.files.filter((item) => item.id !== id)
  recalculateKnowledgeBase(file.knowledgeBaseId)
}

export async function listSessions(options?: {
  knowledgeBaseId?: string
  limit?: number
  offset?: number
  signal?: AbortSignal
}): Promise<ChatSession[]> {
  await delay(260, options?.signal)
  const offset = options?.offset ?? 0
  const limit = options?.limit ?? 50
  const sessions = getMockDatabase()
    .sessions.filter(
      (session) =>
        options?.knowledgeBaseId === undefined ||
        session.knowledgeBaseId === options.knowledgeBaseId,
    )
    .sort(
      (left, right) =>
        right.updatedAt.localeCompare(left.updatedAt) ||
        right.id.localeCompare(left.id),
    )
    .slice(offset, offset + limit)
  return cloneValue(sessions)
}

export async function createSession(knowledgeBaseId: string): Promise<ChatSession> {
  await delay(360)
  requireKnowledgeBase(knowledgeBaseId)
  const timestamp = nextMockTimestamp()
  const session: ChatSession = {
    id: nextMockId('session'),
    knowledgeBaseId,
    title: '新建会话',
    preview: '尚未开始对话',
    createdAt: timestamp,
    updatedAt: timestamp,
    messageCount: 0,
  }
  const database = getMockDatabase()
  database.sessions.unshift(session)
  database.messages[session.id] = []
  return cloneValue(session)
}

function requireSession(id: string, knowledgeBaseId?: string): ChatSession {
  const session = getMockDatabase().sessions.find((item) => item.id === id)
  if (
    session === undefined ||
    (knowledgeBaseId !== undefined && session.knowledgeBaseId !== knowledgeBaseId)
  ) {
    throw new AppError('SESSION_NOT_FOUND', '会话不存在或已被删除。')
  }
  return session
}

export async function getSession(
  id: string,
  knowledgeBaseId: string,
): Promise<ChatSession> {
  await delay(160)
  return cloneValue(requireSession(id, knowledgeBaseId))
}

export async function updateSession(
  id: string,
  knowledgeBaseId: string,
  title: string,
): Promise<ChatSession> {
  await delay(220)
  const normalizedTitle = title.trim()
  if (normalizedTitle.length === 0) {
    throw new AppError('VALIDATION_ERROR', '会话标题不能为空。')
  }
  const session = requireSession(id, knowledgeBaseId)
  session.title = normalizedTitle
  session.updatedAt = nextMockTimestamp()
  return cloneValue(session)
}

export async function deleteSession(
  id: string,
  knowledgeBaseId: string,
): Promise<void> {
  await delay(340)
  const database = getMockDatabase()
  requireSession(id, knowledgeBaseId)
  if (id === 'session-006') {
    throw new AppError(
      'SESSION_DELETE_FAILED',
      '会话删除失败。',
      'Mock session is locked by a deterministic failure fixture.',
    )
  }
  database.sessions = database.sessions.filter((item) => item.id !== id)
  delete database.messages[id]
}

export async function getMessages(
  sessionId: string,
  knowledgeBaseId: string,
  options?: { limit?: number; offset?: number; signal?: AbortSignal },
): Promise<ChatMessage[]> {
  await delay(220, options?.signal)
  requireSession(sessionId, knowledgeBaseId)
  const messages = getMockDatabase().messages[sessionId]
  if (messages === undefined) {
    throw new AppError('SESSION_NOT_FOUND', '会话不存在或已被删除。')
  }
  const offset = options?.offset ?? 0
  const limit = options?.limit ?? 200
  return cloneValue(messages.slice(offset, offset + limit))
}

export async function appendMessage(message: ChatMessage): Promise<ChatMessage> {
  await delay(80)
  const database = getMockDatabase()
  const messages = database.messages[message.sessionId]
  const session = database.sessions.find((item) => item.id === message.sessionId)
  if (messages === undefined || session === undefined) {
    throw new AppError('SESSION_NOT_FOUND', '会话不存在或已被删除。')
  }
  const existingIndex = messages.findIndex((item) => item.id === message.id)
  if (existingIndex >= 0) messages[existingIndex] = cloneValue(message)
  else messages.push(cloneValue(message))
  session.messageCount = messages.length
  session.updatedAt = message.createdAt
  session.preview = message.content.slice(0, 48) || message.errorMessage || '生成失败'
  if (session.title === '新建会话' && message.role === 'user') {
    session.title = message.content.slice(0, 18)
  }
  return cloneValue(message)
}

export async function updateMessageFeedback(
  sessionId: string,
  messageId: string,
  knowledgeBaseId: string,
  feedback: ChatMessage['feedback'],
): Promise<ChatMessage['feedback']> {
  await delay(180)
  requireSession(sessionId, knowledgeBaseId)
  const message = getMockDatabase().messages[sessionId]?.find(
    (item) => item.id === messageId,
  )
  if (
    message === undefined ||
    message.role !== 'assistant' ||
    message.status !== 'complete'
  ) {
    throw new AppError('MESSAGE_NOT_FEEDBACKABLE', '仅可反馈已完成的回答。')
  }
  message.feedback = feedback
  return feedback
}

async function generateMockAnswer(
  question: string,
  handlers: ChatStreamHandlers,
  onDelta: (delta: string) => void,
  audit: RetrievalAudit,
  sources: ChatMessage['sources'],
): Promise<{
  answer: string
  sources: ChatMessage['sources']
  metrics: NonNullable<ChatMessage['metrics']>
}> {
  const deterministicFailure =
    question.includes('触发失败') || question.includes('模型失败')
  const noSources = /无引用|无来源|不存在|量子航海/.test(question)

  await delay(360, handlers.signal)
  if (deterministicFailure) {
    throw new AppError(
      'MODEL_REQUEST_FAILED',
      '模型请求失败。',
      'Model request failed: upstream service unavailable',
    )
  }

  const answer = buildAssistantAnswer(noSources, audit.webSourceCount > 0)
  const chunks = answer.match(/[\s\S]{1,16}/gu) ?? [answer]
  for (const chunk of chunks) {
    await delay(75, handlers.signal)
    onDelta(chunk)
  }
  handlers.onSources(cloneValue(sources))
  return {
    answer,
    sources,
    metrics: {
      retrievalMs: noSources ? 84 : 128,
      generationMs: noSources ? 620 : 1_850,
      totalMs: noSources ? 704 : 1_978,
      promptTokens: noSources ? 212 : 1_228,
      completionTokens: noSources ? 72 : 512,
    },
  }
}

export async function streamChat(
  request: ChatRequest,
  handlers: ChatStreamHandlers,
): Promise<ChatStreamResult> {
  const session = requireSession(request.sessionId, request.knowledgeBaseId)
  const createdAt = nextMockTimestamp()
  const audit = buildMockAudit(
    request.mode,
    request.question,
    requireKnowledgeBase(request.knowledgeBaseId),
    request.topK ?? 5,
  )
  const userMessage: ChatMessage = {
    id: nextMockId('message'),
    sessionId: request.sessionId,
    role: 'user',
    content: request.question.trim(),
    createdAt,
    updatedAt: createdAt,
    status: 'complete',
    sources: [],
    metrics: null,
    feedback: null,
    errorMessage: null,
    errorCode: null,
    replyToMessageId: null,
    ...emptyMockAudit(),
  }
  const assistantMessage: ChatMessage = {
    id: nextMockId('message'),
    sessionId: request.sessionId,
    role: 'assistant',
    content: '',
    createdAt,
    updatedAt: createdAt,
    status: 'streaming',
    sources: [],
    metrics: null,
    feedback: null,
    errorMessage: null,
    errorCode: null,
    replyToMessageId: userMessage.id,
    ...audit,
  }
  await appendMessage(userMessage)
  await appendMessage(assistantMessage)
  handlers.onStart({
    sessionId: session.id,
    userMessageId: userMessage.id,
    assistantMessageId: assistantMessage.id,
    retry: false,
    requestedMode: request.mode,
  })
  handlers.onRetrieval(audit)

  let partial = ''
  try {
    const generated = await generateMockAnswer(
      request.question,
      handlers,
      (delta) => {
        partial += delta
        handlers.onDelta(delta)
      },
      audit,
      mockSourcesForAudit(audit, request.topK ?? 5),
    )
    assistantMessage.content = generated.answer
    assistantMessage.sources = cloneValue(generated.sources)
    assistantMessage.metrics = generated.metrics
    assistantMessage.status = 'complete'
    Object.assign(assistantMessage, audit)
    assistantMessage.updatedAt = nextMockTimestamp()
    await appendMessage(assistantMessage)
    return {
      sessionId: session.id,
      userMessageId: userMessage.id,
      assistantMessageId: assistantMessage.id,
      sources: cloneValue(generated.sources),
      ...audit,
    }
  } catch (caught) {
    assistantMessage.content = partial
    assistantMessage.updatedAt = nextMockTimestamp()
    assistantMessage.status = isAbortError(caught) ? 'cancelled' : 'failed'
    assistantMessage.errorCode = isAbortError(caught)
      ? null
      : caught instanceof AppError
        ? caught.code
        : 'CHAT_STREAM_FAILED'
    assistantMessage.errorMessage = isAbortError(caught)
      ? null
      : caught instanceof Error
        ? caught.message
        : '生成失败'
    await appendMessage(assistantMessage)
    throw caught
  }
}

export async function retryChat(
  request: ChatRetryRequest,
  handlers: ChatStreamHandlers,
): Promise<ChatStreamResult> {
  const session = requireSession(request.sessionId, request.knowledgeBaseId)
  const messages = getMockDatabase().messages[session.id] ?? []
  const assistant = messages.find(
    (message) =>
      message.id === request.assistantMessageId && message.role === 'assistant',
  )
  const user = messages.find((message) => message.id === assistant?.replyToMessageId)
  if (assistant === undefined || user === undefined || user.role !== 'user') {
    throw new AppError('RETRY_MESSAGE_INVALID', '找不到可重试的原问题。')
  }
  handlers.onStart({
    sessionId: session.id,
    userMessageId: user.id,
    assistantMessageId: assistant.id,
    retry: true,
    requestedMode: request.mode,
  })
  const audit = buildMockAudit(
    request.mode,
    user.content,
    requireKnowledgeBase(request.knowledgeBaseId),
    request.topK ?? 5,
  )
  handlers.onRetrieval(audit)

  const generated = await generateMockAnswer(
    user.content,
    handlers,
    handlers.onDelta,
    audit,
    mockSourcesForAudit(audit, request.topK ?? 5),
  )
  assistant.content = generated.answer
  assistant.sources = cloneValue(generated.sources)
  assistant.metrics = generated.metrics
  assistant.status = 'complete'
  assistant.errorCode = null
  assistant.errorMessage = null
  assistant.feedback = null
  assistant.updatedAt = nextMockTimestamp()
  Object.assign(assistant, audit)
  await appendMessage(assistant)
  return {
    sessionId: session.id,
    userMessageId: user.id,
    assistantMessageId: assistant.id,
    sources: cloneValue(generated.sources),
    ...audit,
  }
}

export function cancelChat(
  sessionId: string,
  assistantMessageId: string,
  knowledgeBaseId: string,
): Promise<void> {
  requireSession(sessionId, knowledgeBaseId)
  const assistant = getMockDatabase().messages[sessionId]?.find(
    (message) => message.id === assistantMessageId && message.role === 'assistant',
  )
  if (assistant === undefined) {
    throw new AppError('CHAT_MESSAGE_NOT_FOUND', '助手回答不存在或不属于该会话。')
  }
  // The caller aborts the Mock stream after this acknowledgement. Its existing
  // abort path owns partial-content persistence and the cancelled state.
  return Promise.resolve()
}

export async function executeRetrieval(
  request: RetrievalRequest,
  options?: RequestOptions,
): Promise<RetrievalResponse> {
  await delay(620, options?.signal)
  if (request.query.includes('失败')) {
    throw new AppError(
      'RETRIEVAL_FAILED',
      '检索请求失败。',
      'Mock vector store is temporarily unavailable.',
    )
  }
  if (/无结果|不存在|量子航海/.test(request.query)) {
    return {
      queryTimeMs: 92,
      resultCount: 0,
      results: [],
    }
  }
  const limited = retrievalFixtures
    .filter(
      (item) => request.scoreThreshold === null || item.score >= request.scoreThreshold,
    )
    .slice(0, request.topK)
    .map((item, index) => ({
      rank: index + 1,
      score: item.score,
      fileName: item.fileName,
      fileId: item.fileId,
      chunkId: item.chunkId,
      content: item.content,
      metadata: item.metadata,
    }))
  return cloneValue({
    queryTimeMs: 128,
    resultCount: limited.length,
    results: limited,
  })
}

export async function listIndexes(): Promise<IndexCollection[]> {
  await delay(280)
  return cloneValue(getMockDatabase().indexes)
}

export async function rebuildIndex(
  collectionId: string,
  handlers: RebuildHandlers,
): Promise<IndexCollection> {
  const collection = requireIndex(collectionId)
  if (collection.lifecycle === 'building') {
    throw new AppError('INDEX_BUSY', '该知识库已有索引正在构建。')
  }
  let snapshot: RebuildSnapshot = {
    collectionId,
    progress: 0,
    stepIndex: 0,
    steps: rebuildSteps,
    status: 'building',
    processedFiles: 0,
    totalFiles: collection.fileCount,
  }
  handlers.onProgress(cloneValue(snapshot))

  for (let stepIndex = 0; stepIndex < rebuildSteps.length; stepIndex += 1) {
    await delay(420, handlers.signal)
    const progress = Math.round(((stepIndex + 1) / rebuildSteps.length) * 100)
    snapshot = {
      ...snapshot,
      progress,
      stepIndex,
      processedFiles: Math.min(
        collection.fileCount,
        Math.round((collection.fileCount * progress) / 100),
      ),
      status: progress === 100 ? 'completed' : 'building',
    }
    handlers.onProgress(cloneValue(snapshot))
  }

  const generationNumber =
    Number.parseInt(collection.generation.replace(/\D/gu, ''), 10) + 1
  collection.generation = `G${generationNumber}`
  collection.collectionName = collection.collectionName.replace(
    /g\d+$/u,
    `g${String(generationNumber).padStart(2, '0')}`,
  )
  collection.createdAt = nextMockTimestamp()
  return cloneValue(collection)
}

export async function rollbackIndex(collectionId: string): Promise<IndexCollection[]> {
  await delay(520)
  const database = getMockDatabase()
  const collection = requireIndex(collectionId)
  const previous = database.indexes.find(
    (item) =>
      item.knowledgeBaseId === collection.knowledgeBaseId &&
      item.lifecycle === 'previous',
  )
  if (previous === undefined) {
    throw new AppError('NO_PREVIOUS_INDEX', '没有可回滚的上一版本索引。')
  }
  collection.lifecycle = 'previous'
  previous.lifecycle = 'active'
  return cloneValue(database.indexes)
}

export async function terminateIndex(collectionId: string): Promise<IndexCollection> {
  await delay(360)
  const collection = requireIndex(collectionId)
  if (collection.lifecycle !== 'building') {
    throw new AppError('INDEX_NOT_BUILDING', '该索引当前不在构建中。')
  }
  collection.lifecycle = 'cleanup'
  return cloneValue(collection)
}

export async function cleanupIndex(collectionId: string): Promise<void> {
  await delay(460)
  const database = getMockDatabase()
  const collection = requireIndex(collectionId)
  if (collection.lifecycle === 'active' || collection.lifecycle === 'building') {
    throw new AppError('INDEX_IN_USE', '当前索引不可清理。')
  }
  database.indexes = database.indexes.filter((item) => item.id !== collectionId)
}

export async function getEvaluationMetrics(): Promise<EvaluationMetrics> {
  await delay(240)
  return {
    datasetCount: 6,
    evaluatedQuestions: 1_248,
    averageRetrievalScore: 0.873,
    citationCoverage: 92.6,
    averageDurationMs: 1_840,
  }
}

export async function listEvaluations(): Promise<EvaluationTask[]> {
  await delay(280)
  return cloneValue(getMockDatabase().evaluations)
}

export async function createEvaluation(
  input: EvaluationInput,
): Promise<EvaluationTask> {
  await delay(420)
  requireKnowledgeBase(input.knowledgeBaseId)
  const task: EvaluationTask = {
    id: nextMockId('evaluation'),
    name: input.name.trim(),
    knowledgeBaseId: input.knowledgeBaseId,
    datasetName: input.datasetName,
    questionCount: 120,
    averageScore: null,
    status: 'DRAFT',
    progress: 0,
    createdAt: nextMockTimestamp(),
    completedAt: null,
    results: [],
  }
  getMockDatabase().evaluations.unshift(task)
  return cloneValue(task)
}

export async function runEvaluation(
  id: string,
  handlers: ProgressHandlers,
): Promise<EvaluationTask> {
  const task = getMockDatabase().evaluations.find((item) => item.id === id)
  if (task === undefined) {
    throw new AppError('EVALUATION_NOT_FOUND', '评测任务不存在。')
  }
  if (task.status === 'RUNNING') {
    throw new AppError('EVALUATION_BUSY', '评测任务正在运行。')
  }
  const previousStatus = task.status
  const previousProgress = task.progress
  task.status = 'RUNNING'
  try {
    for (const progress of [12, 28, 46, 68, 84, 100]) {
      await delay(320, handlers.signal)
      task.progress = progress
      handlers.onProgress(progress)
    }
  } catch (error) {
    task.status = previousStatus
    task.progress = previousProgress
    throw error
  }
  task.status = 'COMPLETED'
  task.averageScore = 0.884
  task.completedAt = nextMockTimestamp()
  task.results = cloneValue(
    getMockDatabase().evaluations.find((candidate) => candidate.results.length > 0)
      ?.results ?? [],
  )
  return cloneValue(task)
}
