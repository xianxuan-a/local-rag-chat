<script setup lang="ts">
import {
  Bot,
  ListFilter,
  LoaderCircle,
  MessageSquareText,
  Plus,
  Search,
  Settings2,
  User,
} from 'lucide-vue-next'
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { toast } from 'vue-sonner'

import { chatApi } from '@/api/chatApi'
import { sessionApi } from '@/api/sessionApi'
import ChatInput from '@/components/chat/ChatInput.vue'
import ChatMessageItem from '@/components/chat/ChatMessageItem.vue'
import SessionList from '@/components/chat/SessionList.vue'
import SourceCard from '@/components/chat/SourceCard.vue'
import SourceDrawer from '@/components/chat/SourceDrawer.vue'
import ConfirmDialog from '@/components/common/ConfirmDialog.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import MarkdownContent from '@/components/common/MarkdownContent.vue'
import PageHeader from '@/components/common/PageHeader.vue'
import AppButton from '@/components/ui/AppButton.vue'
import AppSheet from '@/components/ui/AppSheet.vue'
import { useKnowledgeBaseStore } from '@/stores/knowledgeBase'
import { useSessionStore } from '@/stores/session'
import { useSettingsStore } from '@/stores/settings'
import type {
  AnswerFeedback,
  ChatMessage,
  ChatSession,
  RetrievalAudit,
  RetrievalMode,
  SourceReference,
} from '@/types'
import { isAbortError } from '@/utils/abort'
import { getErrorMessage } from '@/utils/error'
import { latestAssistantSources } from '@/utils/chatSources'

const route = useRoute()
const router = useRouter()
const knowledgeBaseStore = useKnowledgeBaseStore()
const sessionStore = useSessionStore()
const settingsStore = useSettingsStore()
const messages = ref<ChatMessage[]>([])
const input = ref('')
const search = ref('')
const loadingMessages = ref(false)
const initializingChat = ref(true)
const generating = ref(false)
const stopping = ref(false)
const generationController = ref<AbortController | null>(null)
const messageController = ref<AbortController | null>(null)
const sessionSheetOpen = ref(false)
const sourcesSheetOpen = ref(false)
const selectedSource = ref<SourceReference | null>(null)
const currentSources = ref<SourceReference[]>([])
const sourceMessageId = ref<string | null>(null)
const selectedMode = ref<RetrievalMode>('knowledge_first')
const deleteTarget = ref<ChatSession | null>(null)
const deleting = ref(false)
const messageScroll = ref<HTMLDivElement | null>(null)
const feedbackBusy = ref(new Set<string>())
const streamDraft = ref<{
  question: string | null
  content: string
  assistantMessageId: string | null
  audit: RetrievalAudit | null
}>()
const generationTarget = ref<{
  sessionId: string
  knowledgeBaseId: string
  assistantMessageId: string | null
} | null>(null)
let messageRequestVersion = 0
let generationRequestVersion = 0

const currentKnowledgeBaseName = computed(
  () => knowledgeBaseStore.current?.name ?? '当前知识库',
)
const chatUnavailableReason = computed(() => {
  if (initializingChat.value || loadingMessages.value) return '正在加载问答状态…'
  if (!knowledgeBaseStore.currentId) return '请先创建知识库并处理文件生成活动索引'
  if (knowledgeBaseStore.current?.status === 'EMPTY')
    return '请先上传并处理文件，生成活动索引'
  if (knowledgeBaseStore.current?.status === 'BUILDING')
    return '知识库索引正在构建，请等待完成'
  if (knowledgeBaseStore.current?.status === 'FAILED')
    return '知识库索引不可用，请先修复或重新构建'
  if (!sessionStore.currentId) return '请先新建会话'
  if (!settingsStore.settings?.chatModel) return '请先在系统设置中配置 Chat 模型'
  return ''
})
const newSessionDisabled = computed(
  () => initializingChat.value || !knowledgeBaseStore.currentId,
)
const modeNotice = computed(() => {
  if (selectedMode.value === 'knowledge_only') return ''
  if (!settingsStore.settings?.webSearchEnabled) {
    return '将降级为仅知识库：全局联网开关已关闭'
  }
  if (!settingsStore.settings.webSearchAllowedForCurrentUser) {
    return '将降级为仅知识库：当前角色无联网资格'
  }
  if (knowledgeBaseStore.current?.webAccessPolicy === 'deny') {
    return '将降级为仅知识库：当前知识库禁止联网'
  }
  if (!settingsStore.settings.webSearchProviderConfigured) {
    return '联网 Provider 未配置，后端将保留本地证据并说明降级'
  }
  return ''
})

const filteredSessions = computed(() => {
  const keyword = search.value.trim().toLowerCase()
  return sessionStore.items.filter(
    (session) =>
      (keyword.length === 0 ||
        session.title.toLowerCase().includes(keyword) ||
        session.preview.toLowerCase().includes(keyword)) &&
      (knowledgeBaseStore.currentId.length === 0 ||
        session.knowledgeBaseId === knowledgeBaseStore.currentId),
  )
})

async function scrollToBottom(): Promise<void> {
  await nextTick()
  if (messageScroll.value) {
    messageScroll.value.scrollTop = messageScroll.value.scrollHeight
  }
}

function matchesCurrentContext(sessionId: string, knowledgeBaseId: string): boolean {
  return (
    sessionStore.currentId === sessionId &&
    knowledgeBaseStore.currentId === knowledgeBaseId
  )
}

function replaceFeedbackBusy(messageId: string, busy: boolean): void {
  const next = new Set(feedbackBusy.value)
  if (busy) next.add(messageId)
  else next.delete(messageId)
  feedbackBusy.value = next
}

async function loadMessages(
  sessionId: string,
  knowledgeBaseId?: string,
): Promise<void> {
  const resolvedKnowledgeBaseId =
    knowledgeBaseId ??
    sessionStore.items.find((session) => session.id === sessionId)?.knowledgeBaseId
  if (resolvedKnowledgeBaseId === undefined) return
  messageController.value?.abort()
  const controller = new AbortController()
  messageController.value = controller
  messageRequestVersion += 1
  const requestVersion = messageRequestVersion
  loadingMessages.value = true
  try {
    const response = await sessionApi.getMessages(sessionId, resolvedKnowledgeBaseId, {
      limit: 200,
      offset: 0,
      signal: controller.signal,
    })
    if (
      requestVersion !== messageRequestVersion ||
      !matchesCurrentContext(sessionId, resolvedKnowledgeBaseId)
    ) {
      return
    }
    messages.value = response
    const activeSources = latestAssistantSources(messages.value)
    sourceMessageId.value = activeSources.messageId
    currentSources.value = activeSources.sources
    await scrollToBottom()
  } catch (caught) {
    if (isAbortError(caught) || requestVersion !== messageRequestVersion) return
    toast.error(getErrorMessage(caught))
    messages.value = []
    sourceMessageId.value = null
    currentSources.value = []
  } finally {
    if (requestVersion === messageRequestVersion) {
      loadingMessages.value = false
      if (messageController.value === controller) messageController.value = null
    }
  }
}

async function selectSession(id: string): Promise<void> {
  const target = sessionStore.items.find((session) => session.id === id)
  if (target === undefined) return
  await cancelGenerationContext()
  messageController.value?.abort()
  sessionStore.setCurrent(id)
  knowledgeBaseStore.setCurrent(target.knowledgeBaseId)
  await router.replace({ path: '/chat', query: { sessionId: id } })
  sessionSheetOpen.value = false
  await loadMessages(id, target.knowledgeBaseId)
}

async function createSession(): Promise<void> {
  if (initializingChat.value || !knowledgeBaseStore.currentId) return
  try {
    const session = await sessionStore.create(knowledgeBaseStore.currentId)
    messages.value = []
    sourceMessageId.value = null
    currentSources.value = []
    sessionSheetOpen.value = false
    toast.success('新会话已创建')
    await router.replace({
      path: '/chat',
      query: { sessionId: session.id },
    })
    await loadMessages(session.id, session.knowledgeBaseId)
  } catch (caught) {
    toast.error(getErrorMessage(caught))
  }
}

async function confirmDelete(): Promise<void> {
  if (deleteTarget.value === null) return
  deleting.value = true
  try {
    await cancelGenerationContext()
    await sessionStore.remove(deleteTarget.value.id, deleteTarget.value.knowledgeBaseId)
    toast.success('会话已删除')
    deleteTarget.value = null
    if (sessionStore.current !== null) {
      knowledgeBaseStore.setCurrent(sessionStore.current.knowledgeBaseId)
      await router.replace({
        path: '/chat',
        query: { sessionId: sessionStore.current.id },
      })
      await loadMessages(sessionStore.current.id, sessionStore.current.knowledgeBaseId)
    } else {
      messages.value = []
      sourceMessageId.value = null
      currentSources.value = []
      await router.replace({ path: '/chat' })
    }
  } catch (caught) {
    toast.error(getErrorMessage(caught))
  } finally {
    deleting.value = false
  }
}

async function cancelGenerationContext(): Promise<void> {
  const target = generationTarget.value
  const controller = generationController.value
  generationRequestVersion += 1
  generationTarget.value = null
  generationController.value = null
  generating.value = false
  stopping.value = false
  streamDraft.value = undefined
  if (target !== null && target.assistantMessageId !== null) {
    try {
      await chatApi.cancel(
        target.sessionId,
        target.assistantMessageId,
        target.knowledgeBaseId,
      )
    } catch {
      // Navigation still aborts the client stream. Startup recovery remains the
      // final guard if the server process disappeared before acknowledging.
    }
  }
  controller?.abort()
}

function generationMatches(
  version: number,
  sessionId: string,
  knowledgeBaseId: string,
): boolean {
  return (
    version === generationRequestVersion &&
    matchesCurrentContext(sessionId, knowledgeBaseId)
  )
}

async function reconcileAfterGeneration(
  version: number,
  sessionId: string,
  knowledgeBaseId: string,
): Promise<void> {
  if (!generationMatches(version, sessionId, knowledgeBaseId)) return
  const assistantMessageId = streamDraft.value?.assistantMessageId ?? null
  for (let attempt = 0; attempt < 75; attempt += 1) {
    await loadMessages(sessionId, knowledgeBaseId)
    if (!generationMatches(version, sessionId, knowledgeBaseId)) return
    const assistant =
      assistantMessageId === null
        ? undefined
        : messages.value.find((message) => message.id === assistantMessageId)
    if (assistant === undefined || assistant.status !== 'streaming') break
    await new Promise<void>((resolve) => window.setTimeout(resolve, 200))
  }
  await sessionStore.load(true)
}

async function sendQuestion(question = input.value.trim()): Promise<void> {
  if (!question || generating.value || !sessionStore.currentId) return
  const sessionId = sessionStore.currentId
  const knowledgeBaseId = sessionStore.current?.knowledgeBaseId
  if (knowledgeBaseId === undefined) return
  const modeSnapshot = selectedMode.value
  input.value = ''
  generationRequestVersion += 1
  const requestVersion = generationRequestVersion
  generating.value = true
  streamDraft.value = {
    question,
    content: '',
    assistantMessageId: null,
    audit: null,
  }
  generationTarget.value = {
    sessionId,
    knowledgeBaseId,
    assistantMessageId: null,
  }
  currentSources.value = []
  sourceMessageId.value = null
  const controller = new AbortController()
  generationController.value = controller
  await scrollToBottom()

  try {
    await chatApi.stream(
      {
        sessionId,
        knowledgeBaseId,
        question,
        topK: settingsStore.settings?.topK ?? 5,
        mode: modeSnapshot,
      },
      {
        signal: controller.signal,
        onStart: (event) => {
          if (!generationMatches(requestVersion, sessionId, knowledgeBaseId)) return
          if (streamDraft.value !== undefined) {
            streamDraft.value.assistantMessageId = event.assistantMessageId
          }
          sourceMessageId.value = event.assistantMessageId
          if (generationTarget.value !== null) {
            generationTarget.value.assistantMessageId = event.assistantMessageId
          }
        },
        onDelta: (delta) => {
          if (!generationMatches(requestVersion, sessionId, knowledgeBaseId)) return
          if (streamDraft.value !== undefined) streamDraft.value.content += delta
          void scrollToBottom()
        },
        onRetrieval: (audit) => {
          if (!generationMatches(requestVersion, sessionId, knowledgeBaseId)) return
          if (streamDraft.value !== undefined) streamDraft.value.audit = audit
        },
        onSources: (sources) => {
          if (!generationMatches(requestVersion, sessionId, knowledgeBaseId)) return
          if (sourceMessageId.value === streamDraft.value?.assistantMessageId) {
            currentSources.value = sources
          }
        },
      },
    )
  } catch (caught) {
    if (
      !isAbortError(caught) &&
      generationMatches(requestVersion, sessionId, knowledgeBaseId)
    ) {
      toast.error(getErrorMessage(caught))
    }
  } finally {
    await reconcileAfterGeneration(requestVersion, sessionId, knowledgeBaseId)
    if (requestVersion === generationRequestVersion) {
      generating.value = false
      if (generationController.value === controller) {
        generationController.value = null
        generationTarget.value = null
      }
      streamDraft.value = undefined
      await scrollToBottom()
    }
  }
}

async function stopGeneration(): Promise<void> {
  const target = generationTarget.value
  const controller = generationController.value
  if (stopping.value || target === null || controller === null) {
    return
  }
  stopping.value = true
  try {
    let assistantMessageId = target.assistantMessageId
    if (assistantMessageId === null) {
      for (let attempt = 0; attempt < 20 && assistantMessageId === null; attempt += 1) {
        const latestMessages = await sessionApi.getMessages(
          target.sessionId,
          target.knowledgeBaseId,
          { limit: 200, offset: 0 },
        )
        assistantMessageId =
          [...latestMessages]
            .reverse()
            .find(
              (message) =>
                message.role === 'assistant' && message.status === 'streaming',
            )?.id ?? null
        if (assistantMessageId === null) {
          await new Promise<void>((resolve) => window.setTimeout(resolve, 50))
        }
      }
      if (assistantMessageId === null) return
      if (generationTarget.value !== null) {
        generationTarget.value.assistantMessageId = assistantMessageId
      }
      if (streamDraft.value !== undefined) {
        streamDraft.value.assistantMessageId = assistantMessageId
      }
    }
    await chatApi.cancel(target.sessionId, assistantMessageId, target.knowledgeBaseId)
    controller.abort()
    let latestMessages: ChatMessage[] = []
    for (let attempt = 0; attempt < 75; attempt += 1) {
      latestMessages = await sessionApi.getMessages(
        target.sessionId,
        target.knowledgeBaseId,
        { limit: 200, offset: 0 },
      )
      const cancelledAssistant = latestMessages.find(
        (message) => message.id === assistantMessageId,
      )
      if (cancelledAssistant?.status !== 'streaming') break
      await new Promise<void>((resolve) => window.setTimeout(resolve, 200))
    }
    if (matchesCurrentContext(target.sessionId, target.knowledgeBaseId)) {
      messages.value = latestMessages
      const activeSources = latestAssistantSources(latestMessages)
      sourceMessageId.value = activeSources.messageId
      currentSources.value = activeSources.sources
      await scrollToBottom()
    }
  } catch (caught) {
    if (!isAbortError(caught)) toast.error(getErrorMessage(caught))
  } finally {
    controller.abort()
    stopping.value = false
  }
}

async function retry(message: ChatMessage): Promise<void> {
  if (
    generating.value ||
    message.role !== 'assistant' ||
    sessionStore.current === null
  ) {
    return
  }
  const sessionId = sessionStore.current.id
  const knowledgeBaseId = sessionStore.current.knowledgeBaseId
  const modeSnapshot = selectedMode.value
  generationRequestVersion += 1
  const requestVersion = generationRequestVersion
  generating.value = true
  currentSources.value = []
  sourceMessageId.value = message.id
  streamDraft.value = {
    question: null,
    content: '',
    assistantMessageId: message.id,
    audit: null,
  }
  generationTarget.value = {
    sessionId,
    knowledgeBaseId,
    assistantMessageId: message.id,
  }
  const controller = new AbortController()
  generationController.value = controller
  await scrollToBottom()
  try {
    await chatApi.retry(
      {
        sessionId,
        knowledgeBaseId,
        assistantMessageId: message.id,
        topK: settingsStore.settings?.topK ?? 5,
        mode: modeSnapshot,
      },
      {
        signal: controller.signal,
        onStart: () => undefined,
        onRetrieval: (audit) => {
          if (!generationMatches(requestVersion, sessionId, knowledgeBaseId)) return
          if (streamDraft.value !== undefined) streamDraft.value.audit = audit
        },
        onDelta: (delta) => {
          if (!generationMatches(requestVersion, sessionId, knowledgeBaseId)) return
          if (streamDraft.value !== undefined) streamDraft.value.content += delta
          void scrollToBottom()
        },
        onSources: (sources) => {
          if (!generationMatches(requestVersion, sessionId, knowledgeBaseId)) return
          if (sourceMessageId.value === message.id) currentSources.value = sources
        },
      },
    )
  } catch (caught) {
    if (
      !isAbortError(caught) &&
      generationMatches(requestVersion, sessionId, knowledgeBaseId)
    ) {
      toast.error(getErrorMessage(caught))
    }
  } finally {
    await reconcileAfterGeneration(requestVersion, sessionId, knowledgeBaseId)
    if (requestVersion === generationRequestVersion) {
      generating.value = false
      if (generationController.value === controller) {
        generationController.value = null
        generationTarget.value = null
      }
      streamDraft.value = undefined
    }
  }
}

async function copyMessage(message: ChatMessage): Promise<void> {
  await navigator.clipboard.writeText(message.content)
  toast.success('回答已复制')
}

async function setFeedback(
  message: ChatMessage,
  feedback: AnswerFeedback,
): Promise<void> {
  const session = sessionStore.current
  if (session === null || feedbackBusy.value.has(message.id)) return
  replaceFeedbackBusy(message.id, true)
  try {
    message.feedback = await chatApi.setFeedback(
      session.id,
      message.id,
      session.knowledgeBaseId,
      feedback,
    )
    toast.success(feedback === null ? '反馈已取消' : '感谢你的反馈')
  } catch (caught) {
    toast.error(getErrorMessage(caught))
  } finally {
    replaceFeedbackBusy(message.id, false)
  }
}

function openSource(source: SourceReference): void {
  selectedSource.value = source
  sourcesSheetOpen.value = false
}

function showSettings(): void {
  toast('当前会话检索参数', {
    description: `${settingsStore.settings?.chatModel ?? '未配置'} · TopK ${settingsStore.settings?.topK ?? 5} · threshold ${settingsStore.settings?.scoreThreshold ?? '无'}`,
  })
}

onMounted(async () => {
  try {
    await Promise.all([
      knowledgeBaseStore.load(),
      sessionStore.load(),
      settingsStore.load(),
    ])
    selectedMode.value =
      settingsStore.settings?.defaultRetrievalMode ?? 'knowledge_first'
    const requestedSession = route.query.sessionId
    if (typeof requestedSession === 'string') {
      const restored = await sessionStore.ensureCurrent(
        requestedSession,
        knowledgeBaseStore.items.map((item) => item.id),
      )
      if (restored === null) {
        toast.error('链接中的会话不存在或无权访问，已恢复最近会话。')
      }
    }
    if (
      sessionStore.current &&
      sessionStore.current.knowledgeBaseId !== knowledgeBaseStore.currentId
    ) {
      knowledgeBaseStore.setCurrent(sessionStore.current.knowledgeBaseId)
    }
    if (sessionStore.current !== null) {
      await router.replace({
        path: '/chat',
        query: { sessionId: sessionStore.current.id },
      })
      await loadMessages(sessionStore.current.id, sessionStore.current.knowledgeBaseId)
    }
  } finally {
    initializingChat.value = false
  }
})

onBeforeUnmount(() => {
  void cancelGenerationContext()
  messageController.value?.abort()
  messageRequestVersion += 1
})
</script>

<template>
  <div
    class="page chat-page"
    :data-generation-state="generating ? 'active' : 'idle'"
    :data-source-message-id="sourceMessageId ?? ''"
  >
    <PageHeader
      title="智能问答"
      description="基于当前知识库进行可追溯、有来源的 RAG 问答"
    >
      <template #actions>
        <span class="badge badge-strong">
          {{ generating ? '生成中' : '生成完成' }}
        </span>
        <AppButton @click="showSettings">
          <Settings2 :size="14" aria-hidden="true" />
          会话设置
        </AppButton>
      </template>
    </PageHeader>

    <div class="chat-shell">
      <aside class="chat-side chat-side-left">
        <div class="side-heading">
          <strong style="font-size: 11px">会话</strong>
          <AppButton
            size="icon"
            variant="primary"
            :disabled="newSessionDisabled"
            :title="!knowledgeBaseStore.currentId ? '请先创建知识库' : undefined"
            aria-label="新建会话"
            @click="createSession"
          >
            <Plus :size="14" aria-hidden="true" />
          </AppButton>
        </div>
        <div class="session-search">
          <label class="search-field" style="display: block; min-width: 0">
            <Search :size="13" aria-hidden="true" />
            <span class="sr-only">搜索会话</span>
            <input v-model="search" class="input" placeholder="搜索会话" />
          </label>
        </div>
        <SessionList
          :sessions="filteredSessions"
          :knowledge-bases="knowledgeBaseStore.items"
          :current-id="sessionStore.currentId"
          allow-delete
          @select="selectSession"
          @remove="deleteTarget = $event"
        />
        <AppButton
          v-if="sessionStore.hasMore"
          style="margin: 10px 12px"
          :disabled="sessionStore.loadingMore"
          @click="sessionStore.loadMore()"
        >
          {{ sessionStore.loadingMore ? '加载中…' : '加载更多会话' }}
        </AppButton>
      </aside>

      <section class="conversation">
        <div class="conversation-bar">
          <div class="truncate">
            <div class="conversation-title">
              {{ sessionStore.current?.title ?? '新建会话' }}
            </div>
            <div class="conversation-meta">
              <strong>{{ currentKnowledgeBaseName }}</strong>
              <span>{{ settingsStore.settings?.chatModel ?? '未配置' }}</span>
              <span>TopK {{ settingsStore.settings?.topK ?? 5 }}</span>
              <span>
                threshold {{ settingsStore.settings?.scoreThreshold ?? '无' }}
              </span>
            </div>
          </div>
          <div class="chat-mobile-actions toolbar-group">
            <AppButton
              size="icon"
              aria-label="打开会话列表"
              @click="sessionSheetOpen = true"
            >
              <ListFilter :size="14" aria-hidden="true" />
            </AppButton>
            <AppButton
              size="icon"
              aria-label="打开引用来源"
              @click="sourcesSheetOpen = true"
            >
              <MessageSquareText :size="14" aria-hidden="true" />
            </AppButton>
          </div>
        </div>

        <div ref="messageScroll" class="message-scroll">
          <div v-if="loadingMessages" class="state-view" style="min-height: 300px">
            <span class="state-icon pulse" />
            <div class="state-title">正在载入会话</div>
          </div>
          <EmptyState
            v-else-if="
              messages.length === 0 &&
              streamDraft === undefined &&
              !knowledgeBaseStore.currentId
            "
            title="请先准备知识库"
            description="创建知识库并处理至少一个文件，生成活动索引后即可开始有来源的问答。"
          >
            <template #actions>
              <AppButton variant="primary" @click="router.push('/knowledge-bases')">
                创建知识库
              </AppButton>
            </template>
          </EmptyState>
          <EmptyState
            v-else-if="
              messages.length === 0 &&
              streamDraft === undefined &&
              !sessionStore.currentId
            "
            title="请先新建会话"
            description="点击会话列表右上角的加号，为当前知识库创建会话。"
          />
          <EmptyState
            v-else-if="messages.length === 0 && streamDraft === undefined"
            title="开始一次有来源的问答"
            description="输入问题后，回答会通过真实流式接口生成，并在完成、停止或失败后从服务器恢复最终状态。"
          />
          <div v-else class="messages">
            <ChatMessageItem
              v-for="message in messages"
              :key="message.id"
              :message="message"
              :action-disabled="generating || feedbackBusy.has(message.id)"
              @copy="copyMessage"
              @retry="retry"
              @regenerate="retry"
              @feedback="setFeedback"
              @source="openSource"
            />
            <article
              v-if="streamDraft?.question"
              class="message message-user"
              aria-label="待确认的用户消息"
            >
              <span class="message-avatar">
                <User :size="14" aria-hidden="true" />
              </span>
              <div class="message-content">
                <div class="message-bubble">{{ streamDraft.question }}</div>
              </div>
            </article>
            <article v-if="streamDraft" class="message" aria-label="正在生成的回答">
              <span class="message-avatar">
                <Bot :size="14" aria-hidden="true" />
              </span>
              <div class="message-content">
                <div class="message-bubble">
                  <div
                    v-if="streamDraft.audit"
                    class="compact-meta"
                    style="margin-bottom: 8px"
                  >
                    实际模式：{{ streamDraft.audit.effectiveMode }} · 本地
                    {{ streamDraft.audit.knowledgeSourceCount }} · 网页
                    {{ streamDraft.audit.webSourceCount }}
                  </div>
                  <MarkdownContent
                    v-if="streamDraft.content"
                    :content="streamDraft.content"
                  />
                  <span
                    style="display: inline-flex; align-items: center; gap: 6px"
                    aria-live="polite"
                  >
                    <LoaderCircle :size="12" class="spin" aria-hidden="true" />
                    <span v-if="!streamDraft.content">正在生成回答</span>
                    <span v-else class="sr-only">回答生成中</span>
                  </span>
                </div>
              </div>
            </article>
          </div>
        </div>

        <ChatInput
          v-model="input"
          v-model:mode="selectedMode"
          :generating="generating"
          :stopping="stopping"
          :stop-disabled="false"
          :disabled="chatUnavailableReason.length > 0"
          :disabled-reason="chatUnavailableReason"
          :knowledge-base-name="currentKnowledgeBaseName"
          :mode-notice="modeNotice"
          @send="sendQuestion()"
          @stop="stopGeneration"
        />
      </section>

      <aside class="chat-side chat-side-right">
        <div class="side-heading">
          <div>
            <strong style="font-size: 11px">引用来源</strong>
            <div class="compact-meta">本轮命中 {{ currentSources.length }} 条</div>
          </div>
          <span class="badge badge-light">{{ currentSources.length }} sources</span>
        </div>
        <div class="source-list">
          <SourceCard
            v-for="(source, index) in currentSources"
            :key="source.reference"
            :source="source"
            :index="index"
            @select="openSource"
          />
          <EmptyState
            v-if="currentSources.length === 0"
            title="暂无有效来源"
            description="当前回答未命中达到阈值的检索分块。"
          />
        </div>
      </aside>
    </div>

    <AppSheet
      v-model:open="sessionSheetOpen"
      title="会话列表"
      description="搜索、切换或创建会话"
    >
      <div class="toolbar-group" style="margin-bottom: 12px">
        <label class="search-field" style="flex: 1">
          <Search :size="13" aria-hidden="true" />
          <span class="sr-only">搜索会话</span>
          <input v-model="search" class="input" placeholder="搜索会话" />
        </label>
        <AppButton
          size="icon"
          variant="primary"
          :disabled="newSessionDisabled"
          :title="!knowledgeBaseStore.currentId ? '请先创建知识库' : undefined"
          aria-label="新建会话"
          @click="createSession"
        >
          <Plus :size="14" aria-hidden="true" />
        </AppButton>
      </div>
      <SessionList
        :sessions="filteredSessions"
        :knowledge-bases="knowledgeBaseStore.items"
        :current-id="sessionStore.currentId"
        allow-delete
        @select="selectSession"
        @remove="deleteTarget = $event"
      />
      <AppButton
        v-if="sessionStore.hasMore"
        style="margin-top: 10px"
        :disabled="sessionStore.loadingMore"
        @click="sessionStore.loadMore()"
      >
        {{ sessionStore.loadingMore ? '加载中…' : '加载更多会话' }}
      </AppButton>
    </AppSheet>

    <AppSheet
      v-model:open="sourcesSheetOpen"
      title="引用来源"
      :description="`本轮命中 ${currentSources.length} 条来源`"
    >
      <SourceCard
        v-for="(source, index) in currentSources"
        :key="source.reference"
        :source="source"
        :index="index"
        @select="openSource"
      />
      <EmptyState
        v-if="currentSources.length === 0"
        title="暂无有效来源"
        description="当前回答没有达到阈值的检索分块。"
      />
    </AppSheet>

    <SourceDrawer
      :open="selectedSource !== null"
      :source="selectedSource"
      @update:open="
        (open) => {
          if (!open) selectedSource = null
        }
      "
    />

    <ConfirmDialog
      :open="deleteTarget !== null"
      title="删除会话？"
      :description="`“${deleteTarget?.title ?? ''}”及其历史消息和反馈将被永久删除。`"
      :busy="deleting"
      @update:open="
        (open) => {
          if (!open) deleteTarget = null
        }
      "
      @confirm="confirmDelete"
    />
  </div>
</template>
