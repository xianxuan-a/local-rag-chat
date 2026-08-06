<script setup lang="ts">
import { RefreshCw, Search, TriangleAlert, Upload } from 'lucide-vue-next'
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { toast } from 'vue-sonner'

import { fileApi } from '@/api/fileApi'
import ConfirmDialog from '@/components/common/ConfirmDialog.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import ErrorState from '@/components/common/ErrorState.vue'
import LoadingState from '@/components/common/LoadingState.vue'
import PageHeader from '@/components/common/PageHeader.vue'
import FileDetailDrawer from '@/components/files/FileDetailDrawer.vue'
import FileTable from '@/components/files/FileTable.vue'
import FileUploadDialog from '@/components/files/FileUploadDialog.vue'
import AppButton from '@/components/ui/AppButton.vue'
import { useKnowledgeBaseStore } from '@/stores/knowledgeBase'
import type { FileRecord, FileStatus } from '@/types'
import { getErrorDetail, getErrorMessage, isCancellationError } from '@/utils/error'

const route = useRoute()
const knowledgeBaseStore = useKnowledgeBaseStore()
const files = ref<FileRecord[]>([])
const loading = ref(true)
const refreshing = ref(false)
const error = ref<unknown>(null)
const search = ref('')
const status = ref<'ALL' | FileStatus>('ALL')
const type = ref('ALL')
const uploadOpen = ref(false)
const uploading = ref(false)
const detailFile = ref<FileRecord | null>(null)
const deleteTarget = ref<FileRecord | null>(null)
const deleting = ref(false)
const controllers = new Map<string, AbortController>()
const processingProgress = ref<Record<string, number>>({})
let listController: AbortController | null = null
let listRequestVersion = 0

const filtered = computed(() => {
  const keyword = search.value.trim().toLowerCase()
  return files.value.filter((file) => {
    const matchesSearch =
      keyword.length === 0 || file.fileName.toLowerCase().includes(keyword)
    const matchesStatus = status.value === 'ALL' || file.status === status.value
    const matchesType = type.value === 'ALL' || file.fileType === type.value
    return matchesSearch && matchesStatus && matchesType
  })
})

const failedFile = computed(
  () => files.value.find((file) => file.status === 'FAILED') ?? null,
)

function replaceFile(updated: FileRecord): void {
  const index = files.value.findIndex((file) => file.id === updated.id)
  if (index >= 0) files.value[index] = updated
  if (detailFile.value?.id === updated.id) detailFile.value = updated
}

async function load(isRefresh = false): Promise<void> {
  const knowledgeBaseId = knowledgeBaseStore.currentId
  listController?.abort()
  const controller = new AbortController()
  listController = controller
  const requestVersion = ++listRequestVersion
  if (!knowledgeBaseId) {
    files.value = []
    loading.value = false
    return
  }
  if (isRefresh) refreshing.value = true
  else loading.value = true
  error.value = null
  try {
    const result = await fileApi.list(knowledgeBaseId, {
      signal: controller.signal,
    })
    if (
      requestVersion === listRequestVersion &&
      knowledgeBaseStore.currentId === knowledgeBaseId
    ) {
      files.value = result
    }
  } catch (caught) {
    if (!isCancellationError(caught) && requestVersion === listRequestVersion) {
      error.value = caught
    }
  } finally {
    if (requestVersion === listRequestVersion) {
      loading.value = false
      refreshing.value = false
    }
  }
}

async function upload(selected: File[]): Promise<void> {
  uploading.value = true
  try {
    for (const file of selected) {
      await fileApi.add(knowledgeBaseStore.currentId, { file })
    }
    await load(true)
    uploadOpen.value = false
    toast.success('文件已上传', {
      description: `已创建 ${selected.length} 条 PENDING 记录。`,
    })
  } catch (caught) {
    toast.error(getErrorMessage(caught))
  } finally {
    uploading.value = false
  }
}

async function process(file: FileRecord): Promise<void> {
  if (controllers.has(file.id)) return
  const controller = new AbortController()
  controllers.set(file.id, controller)
  try {
    const updated = await fileApi.process(file.id, {
      signal: controller.signal,
      onProgress: (progress) => {
        processingProgress.value = {
          ...processingProgress.value,
          [file.id]: progress,
        }
      },
    })
    replaceFile(updated)
    await load(true)
    toast.success('文件处理完成', {
      description: `${updated.fileName} 已生成 ${updated.chunkCount} 个分块。`,
    })
  } catch (caught) {
    if (!isCancellationError(caught)) {
      try {
        replaceFile(await fileApi.get(file.id))
      } catch {
        // The original error is more useful than a refresh failure.
      }
      const detail = getErrorDetail(caught)
      if (detail) {
        toast.error(getErrorMessage(caught), { description: detail })
      } else {
        toast.error(getErrorMessage(caught))
      }
    }
  } finally {
    controllers.delete(file.id)
    const next = { ...processingProgress.value }
    delete next[file.id]
    processingProgress.value = next
  }
}

async function confirmDelete(): Promise<void> {
  if (deleteTarget.value === null) return
  const target = deleteTarget.value
  deleting.value = true
  try {
    await fileApi.remove(target.id)
    await load(true)
    toast.success('文件已删除')
    deleteTarget.value = null
  } catch (caught) {
    toast.error(getErrorMessage(caught))
  } finally {
    deleting.value = false
  }
}

onMounted(async () => {
  await knowledgeBaseStore.load()
  const queryKnowledgeBase = route.query.knowledgeBaseId
  if (typeof queryKnowledgeBase === 'string') {
    knowledgeBaseStore.setCurrent(queryKnowledgeBase)
  }
  await load()
})

watch(
  () => knowledgeBaseStore.currentId,
  () => {
    for (const controller of controllers.values()) controller.abort()
    controllers.clear()
    void load()
  },
)

onBeforeUnmount(() => {
  listController?.abort()
  for (const controller of controllers.values()) controller.abort()
  controllers.clear()
})
</script>

<template>
  <div class="page">
    <PageHeader title="文件管理" description="上传、处理并追踪知识库中的每一份文档">
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
        <AppButton variant="primary" @click="uploadOpen = true">
          <Upload :size="14" aria-hidden="true" />
          上传文件
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
        <div
          v-if="Object.keys(processingProgress).length > 0"
          class="settings-runtime-note"
          style="margin-bottom: 14px"
        >
          <RefreshCw :size="15" aria-hidden="true" />
          <div>
            <strong>服务端文件处理 Job 正在运行</strong>
            <p>
              {{
                Object.entries(processingProgress)
                  .map(([id, progress]) => {
                    const name = files.find((item) => item.id === id)?.fileName ?? id
                    return `${name} ${progress}%`
                  })
                  .join(' · ')
              }}
            </p>
          </div>
        </div>
        <section class="card">
          <div class="toolbar">
            <div class="toolbar-group">
              <label class="search-field">
                <Search :size="14" aria-hidden="true" />
                <span class="sr-only">搜索文件名</span>
                <input v-model="search" class="input" placeholder="搜索文件名" />
              </label>
              <label>
                <span class="sr-only">文件状态</span>
                <select v-model="status" class="native-select">
                  <option value="ALL">全部状态</option>
                  <option value="PENDING">PENDING</option>
                  <option value="PROCESSING">PROCESSING</option>
                  <option value="SUCCESS">SUCCESS</option>
                  <option value="FAILED">FAILED</option>
                </select>
              </label>
              <label>
                <span class="sr-only">文件类型</span>
                <select v-model="type" class="native-select">
                  <option value="ALL">全部类型</option>
                  <option
                    v-for="item in ['PDF', 'TXT', 'CSV', 'JSON', 'MD', 'DOCX']"
                    :key="item"
                  >
                    {{ item }}
                  </option>
                </select>
              </label>
              <AppButton :loading="refreshing" @click="load(true)">
                <RefreshCw :size="14" aria-hidden="true" />
                刷新
              </AppButton>
            </div>
            <div class="toolbar-group">
              <span class="badge badge-light">共 {{ filtered.length }} 个文件</span>
              <AppButton variant="primary" @click="uploadOpen = true">
                <Upload :size="14" aria-hidden="true" />
                上传文件
              </AppButton>
            </div>
          </div>

          <EmptyState
            v-if="filtered.length === 0"
            title="暂无匹配文件"
            description="调整筛选条件，或上传一份支持的文档。"
          >
            <template #actions>
              <AppButton variant="primary" @click="uploadOpen = true">
                <Upload :size="14" aria-hidden="true" />
                上传文件
              </AppButton>
            </template>
          </EmptyState>
          <FileTable
            v-else
            :files="filtered"
            @view="detailFile = $event"
            @process="process"
            @remove="deleteTarget = $event"
          />
        </section>

        <div v-if="failedFile" class="error-banner">
          <div style="display: flex; align-items: center; gap: 10px">
            <TriangleAlert :size="17" aria-hidden="true" />
            <div>
              <div class="table-primary">处理异常</div>
              <div class="compact-meta">
                <strong>{{ failedFile.fileName }}</strong>
                ·
                {{ failedFile.errorMessage }}
              </div>
            </div>
          </div>
          <div class="toolbar-group">
            <AppButton @click="detailFile = failedFile">查看错误</AppButton>
            <AppButton @click="process(failedFile)">
              <RefreshCw :size="14" aria-hidden="true" />
              重试处理
            </AppButton>
          </div>
        </div>
      </template>
    </div>

    <FileUploadDialog v-model:open="uploadOpen" :busy="uploading" @confirm="upload" />
    <FileDetailDrawer
      :open="detailFile !== null"
      :file="detailFile"
      @update:open="
        (open) => {
          if (!open) detailFile = null
        }
      "
    />
    <ConfirmDialog
      :open="deleteTarget !== null"
      title="删除文件？"
      :description="`将从当前数据源删除“${deleteTarget?.fileName ?? ''}”及其受管文件；此操作不可撤销。`"
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
