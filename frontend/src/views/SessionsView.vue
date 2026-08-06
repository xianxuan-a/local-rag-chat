<script setup lang="ts">
import { Check, MessageSquarePlus, Pencil, Search, Trash2, X } from 'lucide-vue-next'
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { toast } from 'vue-sonner'

import { sessionApi } from '@/api/sessionApi'
import SessionList from '@/components/chat/SessionList.vue'
import ConfirmDialog from '@/components/common/ConfirmDialog.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import LoadingState from '@/components/common/LoadingState.vue'
import PageHeader from '@/components/common/PageHeader.vue'
import StatusBadge from '@/components/common/StatusBadge.vue'
import AppButton from '@/components/ui/AppButton.vue'
import { useKnowledgeBaseStore } from '@/stores/knowledgeBase'
import { useSessionStore } from '@/stores/session'
import type { ChatMessage, ChatSession } from '@/types'
import { getErrorMessage } from '@/utils/error'
import { formatDateTime } from '@/utils/format'

const router = useRouter()
const knowledgeBaseStore = useKnowledgeBaseStore()
const sessionStore = useSessionStore()
const messages = ref<ChatMessage[]>([])
const search = ref('')
const knowledgeFilter = ref('ALL')
const loading = ref(true)
const loadingMessages = ref(false)
const deleteTarget = ref<ChatSession | null>(null)
const deleting = ref(false)
const editingTitle = ref(false)
const titleDraft = ref('')
const savingTitle = ref(false)
const messageController = ref<AbortController | null>(null)
let messageRequestVersion = 0

const filteredSessions = computed(() => {
  const keyword = search.value.trim().toLowerCase()
  return sessionStore.items.filter(
    (session) =>
      (keyword.length === 0 ||
        session.title.toLowerCase().includes(keyword) ||
        session.preview.toLowerCase().includes(keyword)) &&
      (knowledgeFilter.value === 'ALL' ||
        session.knowledgeBaseId === knowledgeFilter.value),
  )
})

const currentKnowledgeBase = computed(
  () =>
    knowledgeBaseStore.items.find(
      (item) => item.id === sessionStore.current?.knowledgeBaseId,
    ) ?? null,
)

async function selectSession(id: string): Promise<void> {
  const session = sessionStore.items.find((item) => item.id === id)
  if (session === undefined) return
  messageController.value?.abort()
  messageRequestVersion += 1
  const requestVersion = messageRequestVersion
  sessionStore.setCurrent(id)
  editingTitle.value = false
  loadingMessages.value = true
  try {
    const response = await sessionApi.getMessages(id, session.knowledgeBaseId, {
      limit: 200,
      offset: 0,
      signal: (messageController.value = new AbortController()).signal,
    })
    if (requestVersion !== messageRequestVersion || sessionStore.currentId !== id) {
      return
    }
    messages.value = response
  } catch (caught) {
    if (requestVersion !== messageRequestVersion) return
    toast.error(getErrorMessage(caught))
  } finally {
    if (requestVersion === messageRequestVersion) loadingMessages.value = false
  }
}

async function createSession(): Promise<void> {
  const knowledgeBaseId =
    knowledgeFilter.value === 'ALL'
      ? knowledgeBaseStore.currentId
      : knowledgeFilter.value
  if (!knowledgeBaseId) return
  try {
    const session = await sessionStore.create(knowledgeBaseId)
    await selectSession(session.id)
    toast.success('新会话已创建')
  } catch (caught) {
    toast.error(getErrorMessage(caught))
  }
}

async function confirmDelete(): Promise<void> {
  if (deleteTarget.value === null) return
  deleting.value = true
  try {
    await sessionStore.remove(deleteTarget.value.id, deleteTarget.value.knowledgeBaseId)
    deleteTarget.value = null
    if (sessionStore.currentId) await selectSession(sessionStore.currentId)
    else messages.value = []
    toast.success('会话已删除')
  } catch (caught) {
    toast.error(getErrorMessage(caught))
  } finally {
    deleting.value = false
  }
}

function beginTitleEdit(): void {
  if (sessionStore.current === null) return
  titleDraft.value = sessionStore.current.title
  editingTitle.value = true
}

async function saveTitle(): Promise<void> {
  const session = sessionStore.current
  const normalized = titleDraft.value.trim()
  if (session === null || !normalized || savingTitle.value) return
  savingTitle.value = true
  try {
    await sessionStore.updateTitle(session.id, session.knowledgeBaseId, normalized)
    editingTitle.value = false
    toast.success('会话标题已更新')
  } catch (caught) {
    toast.error(getErrorMessage(caught))
  } finally {
    savingTitle.value = false
  }
}

function continueChat(): void {
  if (!sessionStore.currentId) return
  void router.push({
    path: '/chat',
    query: { sessionId: sessionStore.currentId },
  })
}

onMounted(async () => {
  try {
    await Promise.all([knowledgeBaseStore.load(), sessionStore.load()])
    if (sessionStore.currentId) await selectSession(sessionStore.currentId)
  } finally {
    loading.value = false
  }
})

onBeforeUnmount(() => {
  messageRequestVersion += 1
  messageController.value?.abort()
})
</script>

<template>
  <div class="page">
    <PageHeader title="会话历史" description="检索历史问答、来源引用与耗时信息">
      <template #actions>
        <label style="min-width: 170px">
          <span class="sr-only">知识库筛选</span>
          <select v-model="knowledgeFilter" class="native-select">
            <option value="ALL">全部知识库</option>
            <option
              v-for="item in knowledgeBaseStore.items"
              :key="item.id"
              :value="item.id"
            >
              {{ item.name }}
            </option>
          </select>
        </label>
        <AppButton variant="primary" @click="createSession">
          <MessageSquarePlus :size="14" aria-hidden="true" />
          新建会话
        </AppButton>
      </template>
    </PageHeader>

    <div class="page-content">
      <LoadingState v-if="loading" />
      <div v-else class="session-history">
        <section class="card session-panel">
          <div class="card-header">
            <div>
              <div class="card-title">全部会话</div>
              <div class="card-description">
                共 {{ filteredSessions.length }} 个会话
              </div>
            </div>
            <AppButton
              size="icon"
              variant="primary"
              aria-label="新建会话"
              @click="createSession"
            >
              <MessageSquarePlus :size="14" aria-hidden="true" />
            </AppButton>
          </div>
          <div class="session-search">
            <label class="search-field" style="display: block; min-width: 0">
              <Search :size="13" aria-hidden="true" />
              <span class="sr-only">搜索会话</span>
              <input v-model="search" class="input" placeholder="搜索会话" />
            </label>
          </div>
          <div class="session-panel-list">
            <SessionList
              :sessions="filteredSessions"
              :knowledge-bases="knowledgeBaseStore.items"
              :current-id="sessionStore.currentId"
              allow-delete
              @select="selectSession"
              @remove="deleteTarget = $event"
            />
          </div>
          <AppButton
            v-if="sessionStore.hasMore"
            style="margin: 10px 12px"
            :disabled="sessionStore.loadingMore"
            @click="sessionStore.loadMore()"
          >
            {{ sessionStore.loadingMore ? '加载中…' : '加载更多会话' }}
          </AppButton>
        </section>

        <section class="card session-detail">
          <div v-if="sessionStore.current" class="card-header">
            <div class="truncate">
              <div v-if="editingTitle" class="toolbar-group">
                <input
                  v-model="titleDraft"
                  class="input"
                  maxlength="200"
                  aria-label="会话标题"
                  @keydown.enter.prevent="saveTitle"
                  @keydown.escape.prevent="editingTitle = false"
                />
                <AppButton
                  size="icon"
                  variant="primary"
                  aria-label="保存会话标题"
                  :disabled="savingTitle || !titleDraft.trim()"
                  @click="saveTitle"
                >
                  <Check :size="13" aria-hidden="true" />
                </AppButton>
                <AppButton
                  size="icon"
                  aria-label="取消编辑"
                  :disabled="savingTitle"
                  @click="editingTitle = false"
                >
                  <X :size="13" aria-hidden="true" />
                </AppButton>
              </div>
              <div v-else class="toolbar-group">
                <div class="card-title">{{ sessionStore.current.title }}</div>
                <AppButton
                  size="icon"
                  variant="ghost"
                  aria-label="编辑会话标题"
                  @click="beginTitleEdit"
                >
                  <Pencil :size="12" aria-hidden="true" />
                </AppButton>
              </div>
              <div class="card-description">
                {{ currentKnowledgeBase?.name }} · 创建于
                {{ formatDateTime(sessionStore.current.createdAt) }} ·
                {{ sessionStore.current.messageCount }} 条消息
              </div>
            </div>
            <div class="toolbar-group">
              <AppButton variant="primary" @click="continueChat">继续对话</AppButton>
              <AppButton
                size="icon"
                aria-label="删除当前会话"
                @click="deleteTarget = sessionStore.current"
              >
                <Trash2 :size="14" aria-hidden="true" />
              </AppButton>
            </div>
          </div>

          <div v-if="loadingMessages" class="state-view">
            <span class="state-icon pulse" />
            <div class="state-title">正在载入消息</div>
          </div>
          <EmptyState
            v-else-if="!sessionStore.current || messages.length === 0"
            title="暂无历史消息"
            description="选择其他会话，或继续当前会话开始问答。"
          />
          <div v-else class="session-detail-scroll">
            <article
              v-for="message in messages"
              :key="message.id"
              class="history-message"
            >
              <div class="history-message-head">
                <span class="history-message-role">
                  {{ message.role === 'user' ? '用户' : 'Nexus Assistant' }}
                </span>
                <span>
                  {{ formatDateTime(message.createdAt) }}
                  <template v-if="message.metrics">
                    · {{ (message.metrics.totalMs / 1000).toFixed(2) }} s
                  </template>
                </span>
              </div>
              <div class="history-message-body">
                {{
                  message.status === 'failed' ? message.errorMessage : message.content
                }}
              </div>
              <div
                v-if="message.role === 'assistant'"
                class="toolbar-group"
                style="margin-top: 9px"
              >
                <span
                  v-for="(source, index) in message.sources"
                  :key="source.reference"
                  class="badge badge-light"
                >
                  来源 {{ source.citationNumber || index + 1 }}
                </span>
                <StatusBadge :status="message.status" />
              </div>
            </article>
          </div>
        </section>
      </div>
    </div>

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
