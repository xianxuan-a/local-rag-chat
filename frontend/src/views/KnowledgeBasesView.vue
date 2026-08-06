<script setup lang="ts">
import {
  Database,
  Ellipsis,
  FolderOpen,
  LayoutGrid,
  List,
  Pencil,
  Plus,
  Search,
  Trash2,
} from 'lucide-vue-next'
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { toast } from 'vue-sonner'

import ConfirmDialog from '@/components/common/ConfirmDialog.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import ErrorState from '@/components/common/ErrorState.vue'
import LoadingState from '@/components/common/LoadingState.vue'
import PageHeader from '@/components/common/PageHeader.vue'
import StatusBadge from '@/components/common/StatusBadge.vue'
import AppButton from '@/components/ui/AppButton.vue'
import AppDialog from '@/components/ui/AppDialog.vue'
import AppTooltip from '@/components/ui/AppTooltip.vue'
import { useKnowledgeBaseStore } from '@/stores/knowledgeBase'
import type { KnowledgeBase, KnowledgeBaseInput, KnowledgeBaseStatus } from '@/types'
import { getErrorDetail, getErrorMessage } from '@/utils/error'
import { formatDateTime, formatNumber } from '@/utils/format'

const router = useRouter()
const store = useKnowledgeBaseStore()
const loading = ref(true)
const error = ref<unknown>(null)
const search = ref('')
const statusFilter = ref<'ALL' | KnowledgeBaseStatus>('ALL')
const viewMode = ref<'card' | 'list'>('card')
const dialogOpen = ref(false)
const editing = ref<KnowledgeBase | null>(null)
const submitting = ref(false)
const formError = ref('')
const deleteTarget = ref<KnowledgeBase | null>(null)
const deleting = ref(false)

const form = reactive<KnowledgeBaseInput>({
  name: '',
  description: '',
  webAccessPolicy: 'inherit',
})

const filtered = computed(() => {
  const keyword = search.value.trim().toLowerCase()
  return store.items.filter((item) => {
    const matchesKeyword =
      keyword.length === 0 ||
      item.name.toLowerCase().includes(keyword) ||
      item.description.toLowerCase().includes(keyword)
    const matchesStatus =
      statusFilter.value === 'ALL' || item.status === statusFilter.value
    return matchesKeyword && matchesStatus
  })
})

function openCreate(): void {
  editing.value = null
  form.name = ''
  form.description = ''
  form.webAccessPolicy = 'inherit'
  formError.value = ''
  dialogOpen.value = true
}

function openEdit(item: KnowledgeBase): void {
  editing.value = item
  form.name = item.name
  form.description = item.description
  form.webAccessPolicy = item.webAccessPolicy
  formError.value = ''
  dialogOpen.value = true
}

async function submit(): Promise<void> {
  formError.value = ''
  if (form.name.trim().length < 2) {
    formError.value = '知识库名称至少需要 2 个字符。'
    return
  }
  submitting.value = true
  try {
    if (editing.value === null) {
      await store.create({ ...form })
      toast.success('知识库已创建')
    } else {
      await store.update(editing.value.id, { ...form })
      toast.success('知识库已更新')
    }
    dialogOpen.value = false
  } catch (caught) {
    formError.value = getErrorMessage(caught)
  } finally {
    submitting.value = false
  }
}

async function confirmDelete(): Promise<void> {
  if (deleteTarget.value === null) return
  deleting.value = true
  try {
    await store.remove(deleteTarget.value.id)
    toast.success('知识库已删除')
    deleteTarget.value = null
  } catch (caught) {
    toast.error(getErrorMessage(caught))
  } finally {
    deleting.value = false
  }
}

function openFiles(item: KnowledgeBase): void {
  store.setCurrent(item.id)
  void router.push({ path: '/files', query: { knowledgeBaseId: item.id } })
}

function openIndexes(item: KnowledgeBase): void {
  store.setCurrent(item.id)
  void router.push({ path: '/indexes', query: { knowledgeBaseId: item.id } })
}

async function load(): Promise<void> {
  loading.value = true
  error.value = null
  try {
    await store.load(true)
  } catch (caught) {
    error.value = caught
  } finally {
    loading.value = false
  }
}

onMounted(() => void load())
</script>

<template>
  <div class="page">
    <PageHeader title="知识库" description="管理文档集合、向量索引和问答范围">
      <template #actions>
        <label style="min-width: 170px">
          <span class="sr-only">当前知识库</span>
          <select
            v-model="store.currentId"
            class="native-select"
            @change="store.setCurrent(store.currentId)"
          >
            <option v-for="item in store.items" :key="item.id" :value="item.id">
              {{ item.name }}
            </option>
          </select>
        </label>
        <AppButton variant="primary" @click="openCreate">
          <Plus :size="14" aria-hidden="true" />
          新建知识库
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
        <section class="card">
          <div class="toolbar">
            <div class="toolbar-group">
              <label class="search-field">
                <Search :size="14" aria-hidden="true" />
                <span class="sr-only">搜索知识库</span>
                <input v-model="search" class="input" placeholder="搜索知识库" />
              </label>
              <label>
                <span class="sr-only">按状态筛选</span>
                <select v-model="statusFilter" class="native-select">
                  <option value="ALL">全部状态</option>
                  <option value="READY">READY</option>
                  <option value="BUILDING">BUILDING</option>
                  <option value="FAILED">FAILED</option>
                  <option value="EMPTY">EMPTY</option>
                </select>
              </label>
            </div>
            <div class="toolbar-group">
              <AppButton
                size="sm"
                :variant="viewMode === 'card' ? 'default' : 'ghost'"
                @click="viewMode = 'card'"
              >
                <LayoutGrid :size="13" aria-hidden="true" />
                卡片
              </AppButton>
              <AppButton
                size="sm"
                :variant="viewMode === 'list' ? 'default' : 'ghost'"
                @click="viewMode = 'list'"
              >
                <List :size="13" aria-hidden="true" />
                列表
              </AppButton>
              <AppButton variant="primary" size="sm" @click="openCreate">
                <Plus :size="13" aria-hidden="true" />
                新建知识库
              </AppButton>
            </div>
          </div>
        </section>

        <EmptyState
          v-if="filtered.length === 0"
          title="没有匹配的知识库"
          description="调整搜索或筛选条件，也可以创建一个新的知识库。"
        >
          <template #actions>
            <AppButton variant="primary" @click="openCreate">
              <Plus :size="14" aria-hidden="true" />
              新建知识库
            </AppButton>
          </template>
        </EmptyState>

        <div v-else-if="viewMode === 'card'" class="kb-grid">
          <article v-for="item in filtered" :key="item.id" class="card kb-card">
            <div class="kb-card-top">
              <span class="kb-glyph">
                <Database :size="16" aria-hidden="true" />
              </span>
              <StatusBadge :status="item.status" />
            </div>
            <div class="kb-name">{{ item.name }}</div>
            <div class="kb-description line-clamp-2">
              {{ item.description }}
            </div>
            <div class="kb-stats">
              <div class="kb-stat">
                <div class="kb-stat-value">{{ formatNumber(item.fileCount) }}</div>
                <div class="kb-stat-label">文件</div>
              </div>
              <div class="kb-stat">
                <div class="kb-stat-value">
                  {{ formatNumber(item.chunkCount) }}
                </div>
                <div class="kb-stat-label">chunks</div>
              </div>
              <div class="kb-stat">
                <div class="kb-stat-value mono" style="font-size: 8px">
                  {{ item.embeddingModel }}
                </div>
                <div class="kb-stat-label">向量模型</div>
              </div>
            </div>
            <div class="kb-card-foot">
              <span>更新于 {{ formatDateTime(item.updatedAt) }}</span>
              <div class="toolbar-group">
                <AppButton size="sm" variant="ghost" @click="openFiles(item)">
                  <FolderOpen :size="13" aria-hidden="true" />
                  打开
                </AppButton>
                <AppTooltip text="编辑知识库">
                  <AppButton
                    size="icon"
                    variant="ghost"
                    aria-label="编辑知识库"
                    @click="openEdit(item)"
                  >
                    <Pencil :size="13" aria-hidden="true" />
                  </AppButton>
                </AppTooltip>
                <AppTooltip text="删除知识库">
                  <AppButton
                    size="icon"
                    variant="ghost"
                    aria-label="删除知识库"
                    @click="deleteTarget = item"
                  >
                    <Trash2 :size="13" aria-hidden="true" />
                  </AppButton>
                </AppTooltip>
                <AppTooltip text="更多操作">
                  <AppButton
                    size="icon"
                    variant="ghost"
                    aria-label="查看索引"
                    @click="openIndexes(item)"
                  >
                    <Ellipsis :size="14" aria-hidden="true" />
                  </AppButton>
                </AppTooltip>
              </div>
            </div>
          </article>
        </div>

        <section v-else class="card" style="margin-top: 14px">
          <div class="table-scroll">
            <table class="data-table">
              <thead>
                <tr>
                  <th>知识库</th>
                  <th>状态</th>
                  <th>文件数</th>
                  <th>分块数</th>
                  <th>向量模型</th>
                  <th>更新时间</th>
                  <th style="text-align: right">操作</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="item in filtered" :key="item.id">
                  <td>
                    <div class="table-primary">{{ item.name }}</div>
                    <div class="compact-meta">{{ item.description }}</div>
                  </td>
                  <td><StatusBadge :status="item.status" /></td>
                  <td>{{ formatNumber(item.fileCount) }}</td>
                  <td>{{ formatNumber(item.chunkCount) }}</td>
                  <td class="mono">{{ item.embeddingModel }}</td>
                  <td>{{ formatDateTime(item.updatedAt) }}</td>
                  <td>
                    <div class="table-actions">
                      <AppButton size="sm" @click="openFiles(item)">打开</AppButton>
                      <AppButton size="sm" variant="ghost" @click="openEdit(item)">
                        编辑
                      </AppButton>
                      <AppButton
                        size="icon"
                        variant="ghost"
                        aria-label="删除知识库"
                        @click="deleteTarget = item"
                      >
                        <Trash2 :size="13" aria-hidden="true" />
                      </AppButton>
                    </div>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>
      </template>
    </div>

    <AppDialog
      v-model:open="dialogOpen"
      :title="editing ? '编辑知识库' : '新建知识库'"
      description="填写名称和说明，创建结果由当前数据源保存。"
    >
      <div class="form-field">
        <label class="form-label" for="kb-name">知识库名称</label>
        <input
          id="kb-name"
          v-model="form.name"
          class="input"
          placeholder="例如：产品发布资料"
          :aria-invalid="Boolean(formError)"
        />
      </div>
      <div class="form-field">
        <label class="form-label" for="kb-description">描述</label>
        <textarea
          id="kb-description"
          v-model="form.description"
          class="textarea"
          placeholder="说明文档范围和主要用途"
        />
      </div>
      <div class="form-field">
        <label class="form-label" for="kb-web-policy">联网策略</label>
        <select id="kb-web-policy" v-model="form.webAccessPolicy" class="native-select">
          <option value="inherit">继承全局设置</option>
          <option value="allow">允许联网（仍受全局和角色限制）</option>
          <option value="deny">禁止联网</option>
        </select>
      </div>
      <p v-if="formError" class="form-error" role="alert">{{ formError }}</p>
      <template #footer>
        <AppButton @click="dialogOpen = false">取消</AppButton>
        <AppButton variant="primary" :loading="submitting" @click="submit">
          {{ editing ? '保存修改' : '创建知识库' }}
        </AppButton>
      </template>
    </AppDialog>

    <ConfirmDialog
      :open="deleteTarget !== null"
      title="删除知识库？"
      :description="`将删除“${deleteTarget?.name ?? ''}”。包含文件或会话时，服务端会拒绝此操作。`"
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
