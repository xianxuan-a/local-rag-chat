<script setup lang="ts">
import {
  ArchiveRestore,
  Eye,
  Layers3,
  RefreshCw,
  Search,
  Square,
  Trash2,
} from 'lucide-vue-next'
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { toast } from 'vue-sonner'

import { indexApi } from '@/api/indexApi'
import EmptyState from '@/components/common/EmptyState.vue'
import ErrorState from '@/components/common/ErrorState.vue'
import LoadingState from '@/components/common/LoadingState.vue'
import PageHeader from '@/components/common/PageHeader.vue'
import StatusBadge from '@/components/common/StatusBadge.vue'
import IndexDetailDrawer from '@/components/indexes/IndexDetailDrawer.vue'
import IndexStatusBadge from '@/components/indexes/IndexStatusBadge.vue'
import AppButton from '@/components/ui/AppButton.vue'
import AppTooltip from '@/components/ui/AppTooltip.vue'
import { useKnowledgeBaseStore } from '@/stores/knowledgeBase'
import { useAuthStore } from '@/stores/auth'
import type { DurableJob, IndexCollection, IndexLifecycle, IndexState } from '@/types'
import { isAbortError } from '@/utils/abort'
import { getErrorDetail, getErrorMessage } from '@/utils/error'
import { formatDateTime, formatNumber } from '@/utils/format'

const knowledgeBaseStore = useKnowledgeBaseStore()
const authStore = useAuthStore()
const states = ref<IndexState[]>([])
const loading = ref(true)
const error = ref<unknown>(null)
const search = ref('')
const lifecycle = ref<'ALL' | IndexLifecycle>('ALL')
const detail = ref<IndexCollection | null>(null)
const activeJob = ref<DurableJob | null>(null)
const requestController = ref<AbortController | null>(null)
let pollTimer: number | null = null

const currentState = computed(
  () =>
    states.value.find(
      (item) => item.knowledgeBaseId === knowledgeBaseStore.currentId,
    ) ?? null,
)
const indexes = computed(() => states.value.flatMap((item) => item.collections))
const filtered = computed(() => {
  const keyword = search.value.trim().toLowerCase()
  return indexes.value.filter(
    (item) =>
      (keyword.length === 0 || item.collectionName.toLowerCase().includes(keyword)) &&
      (lifecycle.value === 'ALL' || item.lifecycle === lifecycle.value),
  )
})
const counts = computed(() => ({
  active: indexes.value.filter((item) => item.lifecycle === 'active').length,
  previous: indexes.value.filter((item) => item.lifecycle === 'previous').length,
  building: indexes.value.filter((item) => item.lifecycle === 'building').length,
  cleanup: indexes.value.filter((item) => item.lifecycle === 'cleanup').length,
  orphan: indexes.value.filter((item) => item.lifecycle === 'orphan').length,
}))
const jobIsRunning = computed(
  () =>
    activeJob.value !== null &&
    ['QUEUED', 'RUNNING', 'CANCEL_REQUESTED'].includes(activeJob.value.status),
)

function knowledgeBaseName(id: string): string {
  return (
    states.value.find((item) => item.knowledgeBaseId === id)?.knowledgeBaseName ??
    '未知知识库'
  )
}

function stopPolling(): void {
  if (pollTimer !== null) window.clearTimeout(pollTimer)
  pollTimer = null
  requestController.value?.abort()
  requestController.value = null
}

async function load(showLoading = true): Promise<void> {
  stopPolling()
  if (showLoading) loading.value = true
  error.value = null
  const controller = new AbortController()
  requestController.value = controller
  try {
    await knowledgeBaseStore.load()
    states.value = await indexApi.listStates(undefined, controller.signal)
    const job = currentState.value?.latestJob ?? null
    activeJob.value = job
    if (
      job !== null &&
      ['QUEUED', 'RUNNING', 'CANCEL_REQUESTED'].includes(job.status)
    ) {
      pollTimer = window.setTimeout(() => void pollJob(job.id), 700)
    }
  } catch (caught) {
    if (!isAbortError(caught)) error.value = caught
  } finally {
    if (requestController.value === controller) requestController.value = null
    if (showLoading) loading.value = false
  }
}

async function pollJob(jobId: string): Promise<void> {
  const controller = new AbortController()
  requestController.value = controller
  try {
    const job = await indexApi.getJob(jobId, controller.signal)
    activeJob.value = job
    if (['QUEUED', 'RUNNING', 'CANCEL_REQUESTED'].includes(job.status)) {
      pollTimer = window.setTimeout(() => void pollJob(jobId), 700)
    } else {
      await load(false)
    }
  } catch (caught) {
    if (!isAbortError(caught)) error.value = caught
  } finally {
    if (requestController.value === controller) requestController.value = null
  }
}

async function rebuildCurrent(): Promise<void> {
  const state = currentState.value
  if (!state || jobIsRunning.value) return
  try {
    activeJob.value = await indexApi.submitRebuild(state.knowledgeBaseId)
    toast.success('索引重建已提交')
    pollTimer = window.setTimeout(() => void pollJob(activeJob.value!.id), 200)
  } catch (caught) {
    toast.error(getErrorMessage(caught))
  }
}

async function requestCancel(): Promise<void> {
  if (!activeJob.value || !jobIsRunning.value) return
  try {
    activeJob.value = await indexApi.cancelJob(activeJob.value.id)
    toast.success(
      activeJob.value.status === 'CANCELLED'
        ? '排队任务已取消'
        : '已请求取消，运行中的任务会在下一个检查点停止',
    )
  } catch (caught) {
    toast.error(getErrorMessage(caught))
  }
}

async function abortBuilding(item: IndexCollection): Promise<void> {
  if (
    !window.confirm(
      `确认清理遗留候选 ${item.collectionName}？该操作仅在维护 Job 已终态后执行。`,
    )
  ) {
    return
  }
  try {
    await indexApi.abortBuilding(item.knowledgeBaseId)
    await load(false)
    toast.success('遗留候选已清理')
  } catch (caught) {
    toast.error(getErrorMessage(caught))
  }
}

async function rollback(item: IndexCollection): Promise<void> {
  if (
    !window.confirm('确认回滚到 previous Collection？当前 active 将成为 previous。')
  ) {
    return
  }
  try {
    await indexApi.rollbackKnowledgeBase(item.knowledgeBaseId)
    await load(false)
    toast.success('已回滚到上一版本索引')
  } catch (caught) {
    toast.error(getErrorMessage(caught))
  }
}

async function cleanup(item: IndexCollection): Promise<void> {
  const previous = item.lifecycle === 'previous'
  const orphan = item.lifecycle === 'orphan'
  if (
    !window.confirm(
      previous
        ? '确认永久放弃 previous 回滚版本？'
        : `确认请求安全清理知识库的孤立 Collection？后端会再次验证引用与生命周期。`,
    )
  ) {
    return
  }
  try {
    activeJob.value = await indexApi.cleanupKnowledgeBase(
      item.knowledgeBaseId,
      previous,
      orphan,
    )
    toast.success('清理任务已提交')
    pollTimer = window.setTimeout(() => void pollJob(activeJob.value!.id), 200)
  } catch (caught) {
    toast.error(getErrorMessage(caught))
  }
}

watch(
  () => knowledgeBaseStore.currentId,
  () => {
    activeJob.value = currentState.value?.latestJob ?? null
  },
)
onMounted(() => void load())
onBeforeUnmount(stopPolling)
</script>

<template>
  <div class="page">
    <PageHeader
      title="索引管理"
      description="查看真实 Collection 指针、维护 Job 和安全清理状态"
    >
      <template #actions>
        <label style="min-width: 170px">
          <span class="sr-only">当前知识库</span>
          <select v-model="knowledgeBaseStore.currentId" class="native-select">
            <option
              v-for="item in knowledgeBaseStore.items"
              :key="item.id"
              :value="item.id"
            >
              {{ item.name }}
            </option>
          </select>
        </label>
        <AppButton
          v-if="authStore.isAdmin"
          variant="primary"
          :disabled="currentState === null || jobIsRunning"
          @click="rebuildCurrent"
        >
          <RefreshCw :size="14" aria-hidden="true" />
          重建索引
        </AppButton>
      </template>
    </PageHeader>

    <div class="page-content">
      <LoadingState v-if="loading" />
      <ErrorState
        v-else-if="error"
        :message="getErrorMessage(error)"
        :detail="getErrorDetail(error)"
        @retry="load"
      />
      <template v-else>
        <div class="index-summary">
          <section
            v-for="item in [
              { key: 'active', label: 'ACTIVE', value: counts.active },
              { key: 'previous', label: 'PREVIOUS', value: counts.previous },
              { key: 'building', label: 'BUILDING', value: counts.building },
              { key: 'cleanup', label: 'CLEANUP', value: counts.cleanup },
              { key: 'orphan', label: 'ORPHAN', value: counts.orphan },
            ]"
            :key="item.key"
            class="card index-summary-card"
          >
            <span class="index-summary-icon"><Layers3 :size="16" /></span>
            <div>
              <div class="index-summary-value">{{ item.value }}</div>
              <div class="index-summary-label">{{ item.label }}</div>
            </div>
            <StatusBadge :status="item.key" style="margin-left: auto" />
          </section>
        </div>

        <section v-if="activeJob" class="card">
          <div class="card-header">
            <div>
              <h2 class="card-title">最近维护 Job</h2>
              <p class="card-description">
                {{ activeJob.stage ?? '等待 Worker' }} · {{ activeJob.progress }}%
              </p>
            </div>
            <div class="table-actions">
              <StatusBadge :status="activeJob.status" />
              <AppButton
                v-if="authStore.isAdmin && jobIsRunning"
                size="sm"
                @click="requestCancel"
              >
                <Square :size="12" />
                请求取消
              </AppButton>
            </div>
          </div>
          <div class="progress" :aria-label="`维护进度 ${activeJob.progress}%`">
            <div class="progress-bar" :style="{ width: `${activeJob.progress}%` }" />
          </div>
          <p v-if="activeJob.errorMessage" class="form-error">
            {{ activeJob.errorCode }}：{{ activeJob.errorMessage }}
          </p>
        </section>

        <section class="card">
          <div class="toolbar">
            <div class="toolbar-group">
              <label class="search-field">
                <Search :size="14" />
                <span class="sr-only">搜索 Collection</span>
                <input v-model="search" class="input" placeholder="搜索 Collection" />
              </label>
              <select
                v-model="lifecycle"
                class="native-select"
                aria-label="生命周期筛选"
              >
                <option value="ALL">全部生命周期</option>
                <option
                  v-for="value in [
                    'active',
                    'previous',
                    'building',
                    'cleanup',
                    'orphan',
                  ]"
                  :key="value"
                  :value="value"
                >
                  {{ value }}
                </option>
              </select>
            </div>
          </div>

          <EmptyState
            v-if="filtered.length === 0"
            title="暂无索引"
            description="当前筛选下没有服务器 Collection。"
          />
          <div v-else class="table-scroll">
            <table class="data-table">
              <thead>
                <tr>
                  <th>Collection 名称</th>
                  <th>知识库</th>
                  <th>角色</th>
                  <th>Generation</th>
                  <th>文件数</th>
                  <th>分块数</th>
                  <th>时间</th>
                  <th style="text-align: right">操作</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="item in filtered"
                  :key="`${item.knowledgeBaseId}-${item.collectionName}`"
                >
                  <td>
                    <div class="table-primary mono">{{ item.collectionName }}</div>
                    <div v-if="item.error" class="table-subcopy">{{ item.error }}</div>
                  </td>
                  <td>{{ knowledgeBaseName(item.knowledgeBaseId) }}</td>
                  <td><IndexStatusBadge :status="item.lifecycle" /></td>
                  <td>{{ item.generation }}</td>
                  <td>{{ item.exists ? formatNumber(item.fileCount) : '不存在' }}</td>
                  <td>{{ item.exists ? formatNumber(item.chunkCount) : '—' }}</td>
                  <td>{{ item.createdAt ? formatDateTime(item.createdAt) : '—' }}</td>
                  <td>
                    <div class="table-actions">
                      <AppTooltip text="查看详细配置">
                        <AppButton
                          size="icon"
                          variant="ghost"
                          aria-label="查看索引详情"
                          @click="detail = item"
                        >
                          <Eye :size="13" />
                        </AppButton>
                      </AppTooltip>
                      <AppTooltip
                        v-if="authStore.isAdmin && item.lifecycle === 'previous'"
                        text="回滚"
                      >
                        <AppButton
                          size="icon"
                          variant="ghost"
                          :disabled="jobIsRunning"
                          aria-label="回滚索引"
                          @click="rollback(item)"
                        >
                          <ArchiveRestore :size="13" />
                        </AppButton>
                      </AppTooltip>
                      <AppTooltip
                        v-if="authStore.isAdmin && item.lifecycle === 'building'"
                        text="清理遗留候选"
                      >
                        <AppButton
                          size="icon"
                          variant="ghost"
                          :disabled="jobIsRunning"
                          aria-label="清理遗留候选"
                          @click="abortBuilding(item)"
                        >
                          <Square :size="12" />
                        </AppButton>
                      </AppTooltip>
                      <AppTooltip
                        v-if="
                          authStore.isAdmin &&
                          (item.lifecycle === 'previous' || item.lifecycle === 'orphan')
                        "
                        :text="item.cleanupReason ?? '安全清理'"
                      >
                        <AppButton
                          size="icon"
                          variant="ghost"
                          :disabled="jobIsRunning || !item.safeToCleanup"
                          aria-label="清理索引"
                          @click="cleanup(item)"
                        >
                          <Trash2 :size="13" />
                        </AppButton>
                      </AppTooltip>
                    </div>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>
      </template>
    </div>

    <IndexDetailDrawer
      :open="detail !== null"
      :index="detail"
      :knowledge-bases="knowledgeBaseStore.items"
      @update:open="
        (open) => {
          if (!open) detail = null
        }
      "
    />
  </div>
</template>
