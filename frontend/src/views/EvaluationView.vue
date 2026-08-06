<script setup lang="ts">
import {
  Clock3,
  FileQuestion,
  ListChecks,
  Plus,
  Search,
  Square,
  Target,
} from 'lucide-vue-next'
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { toast } from 'vue-sonner'

import { evaluationApi } from '@/api/evaluationApi'
import EmptyState from '@/components/common/EmptyState.vue'
import ErrorState from '@/components/common/ErrorState.vue'
import LoadingState from '@/components/common/LoadingState.vue'
import MetricCard from '@/components/common/MetricCard.vue'
import PageHeader from '@/components/common/PageHeader.vue'
import StatusBadge from '@/components/common/StatusBadge.vue'
import AppButton from '@/components/ui/AppButton.vue'
import AppDialog from '@/components/ui/AppDialog.vue'
import { useKnowledgeBaseStore } from '@/stores/knowledgeBase'
import type {
  EvaluationCase,
  EvaluationDataset,
  EvaluationMode,
  EvaluationRun,
  EvaluationSummary,
} from '@/types'
import { isAbortError } from '@/utils/abort'
import { getErrorDetail, getErrorMessage } from '@/utils/error'
import { formatDateTime, formatDuration, formatNumber } from '@/utils/format'

const knowledgeBaseStore = useKnowledgeBaseStore()
const datasets = ref<EvaluationDataset[]>([])
const runs = ref<EvaluationRun[]>([])
const summary = ref<EvaluationSummary | null>(null)
const selectedRun = ref<EvaluationRun | null>(null)
const cases = ref<EvaluationCase[]>([])
const selectedCaseIndex = ref(0)
const failedOnly = ref(false)
const loading = ref(true)
const casesLoading = ref(false)
const error = ref<unknown>(null)
const search = ref('')
const createOpen = ref(false)
const submitting = ref(false)
const formError = ref('')
const datasetFile = ref<File | null>(null)
const requestController = ref<AbortController | null>(null)
let pollTimer: number | null = null

interface EvaluationForm {
  name: string
  knowledgeBaseId: string
  datasetId: string
  datasetName: string
  datasetDescription: string
  mode: EvaluationMode
  topK: number
  scoreThreshold: number | null
}

const form = reactive<EvaluationForm>({
  name: '',
  knowledgeBaseId: '',
  datasetId: '',
  datasetName: '',
  datasetDescription: '',
  mode: 'retrieval',
  topK: 4,
  scoreThreshold: null as number | null,
})

const filteredRuns = computed(() => {
  const keyword = search.value.trim().toLowerCase()
  return runs.value.filter(
    (run) =>
      !keyword ||
      run.name.toLowerCase().includes(keyword) ||
      (run.dataset?.name.toLowerCase().includes(keyword) ?? false),
  )
})
const selectedCase = computed(
  () =>
    cases.value.find((item) => item.index === selectedCaseIndex.value) ??
    cases.value[0] ??
    null,
)
const metricCards = computed(() => [
  {
    label: '评测数据集',
    value: summary.value?.datasetCount ?? 0,
    delta: '',
    note: '服务器持久化',
    icon: ListChecks,
    formatter: formatNumber,
  },
  {
    label: '评测运行',
    value: summary.value?.runCount ?? 0,
    delta: '',
    note: '历史运行',
    icon: FileQuestion,
    formatter: formatNumber,
  },
  {
    label: '执行中',
    value:
      (summary.value?.statusCounts.QUEUED ?? 0) +
      (summary.value?.statusCounts.RUNNING ?? 0) +
      (summary.value?.statusCounts.CANCEL_REQUESTED ?? 0),
    delta: '',
    note: '真实 Job 状态',
    icon: Clock3,
    formatter: formatNumber,
  },
  {
    label: '部分成功',
    value: runs.value.filter((item) => item.outcome === 'PARTIAL_SUCCESS').length,
    delta: '',
    note: '含失败案例',
    icon: Target,
    formatter: formatNumber,
  },
])
const selectedRetrievalMetrics = computed(() => {
  const retrieval = selectedRun.value?.metrics?.retrieval
  return typeof retrieval === 'object' && retrieval !== null
    ? (retrieval as Record<string, unknown>)
    : null
})

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
  try {
    await knowledgeBaseStore.load()
    const [nextDatasets, nextRuns, nextSummary] = await Promise.all([
      evaluationApi.listDatasets(),
      evaluationApi.listRuns(),
      evaluationApi.getSummary(),
    ])
    datasets.value = nextDatasets
    runs.value = nextRuns
    summary.value = nextSummary
    form.knowledgeBaseId = knowledgeBaseStore.currentId
    form.datasetId = nextDatasets[0]?.id ?? ''
    const selected =
      (selectedRun.value &&
        nextRuns.find((item) => item.id === selectedRun.value?.id)) ||
      nextRuns[0] ||
      null
    if (selected) await selectRun(selected)
    const live = nextRuns.find((item) =>
      ['QUEUED', 'RUNNING', 'CANCEL_REQUESTED'].includes(item.status),
    )
    if (live) pollTimer = window.setTimeout(() => void pollRun(live.id), 700)
  } catch (caught) {
    if (!isAbortError(caught)) error.value = caught
  } finally {
    if (showLoading) loading.value = false
  }
}

async function pollRun(id: string): Promise<void> {
  const controller = new AbortController()
  requestController.value = controller
  try {
    const run = await evaluationApi.getRun(id, controller.signal)
    const index = runs.value.findIndex((item) => item.id === id)
    if (index >= 0) runs.value[index] = run
    if (selectedRun.value?.id === id) selectedRun.value = run
    if (['QUEUED', 'RUNNING', 'CANCEL_REQUESTED'].includes(run.status)) {
      pollTimer = window.setTimeout(() => void pollRun(id), 700)
    } else {
      await load(false)
    }
  } catch (caught) {
    if (!isAbortError(caught)) error.value = caught
  } finally {
    if (requestController.value === controller) requestController.value = null
  }
}

async function selectRun(run: EvaluationRun): Promise<void> {
  selectedRun.value =
    run.status === 'SUCCEEDED' ? await evaluationApi.getRun(run.id) : run
  cases.value = []
  if (run.status !== 'SUCCEEDED') return
  casesLoading.value = true
  try {
    cases.value = await evaluationApi.listCases(run.id, {
      failedOnly: failedOnly.value,
      limit: 200,
      offset: 0,
    })
    selectedCaseIndex.value = cases.value[0]?.index ?? 0
  } catch (caught) {
    toast.error(getErrorMessage(caught))
  } finally {
    casesLoading.value = false
  }
}

async function toggleFailedOnly(): Promise<void> {
  if (selectedRun.value) await selectRun(selectedRun.value)
}

function openCreate(): void {
  form.name = ''
  form.knowledgeBaseId = knowledgeBaseStore.currentId
  form.datasetId = datasets.value[0]?.id ?? ''
  form.datasetName = ''
  form.datasetDescription = ''
  form.mode = 'retrieval'
  form.topK = 4
  form.scoreThreshold = null
  datasetFile.value = null
  formError.value = ''
  createOpen.value = true
}

function chooseDatasetFile(event: Event): void {
  const input = event.target as HTMLInputElement
  datasetFile.value = input.files?.[0] ?? null
}

async function createRun(): Promise<void> {
  formError.value = ''
  if (!form.name.trim() || !form.knowledgeBaseId) {
    formError.value = '请填写运行名称并选择知识库。'
    return
  }
  submitting.value = true
  try {
    let datasetId = form.datasetId
    if (datasetFile.value) {
      if (!form.datasetName.trim()) {
        throw new Error('上传新数据集时必须填写数据集名称。')
      }
      const uploaded = await evaluationApi.uploadDataset({
        name: form.datasetName,
        description: form.datasetDescription,
        file: datasetFile.value,
      })
      datasets.value.unshift(uploaded)
      datasetId = uploaded.id
    }
    if (!datasetId) throw new Error('请选择或上传评测数据集。')
    const caseCount =
      datasets.value.find((item) => item.id === datasetId)?.caseCount ?? 1
    const callsPerCase = form.mode === 'rag' ? 2 : 1
    const created = await evaluationApi.createRun({
      datasetId,
      knowledgeBaseId: form.knowledgeBaseId,
      name: form.name,
      mode: form.mode,
      topK: form.topK,
      scoreThreshold: form.scoreThreshold,
      maxCalls: Math.max(200, caseCount * callsPerCase),
      maxGenerationTokens: form.mode === 'rag' ? Math.max(100000, caseCount * 1024) : 0,
      maxRuntimeSeconds: 1800,
    })
    runs.value.unshift(created)
    selectedRun.value = created
    createOpen.value = false
    toast.success('真实评测运行已提交')
    pollTimer = window.setTimeout(() => void pollRun(created.id), 300)
  } catch (caught) {
    formError.value = getErrorMessage(caught)
  } finally {
    submitting.value = false
  }
}

async function cancelRun(run: EvaluationRun): Promise<void> {
  try {
    await evaluationApi.cancel(run.id)
    toast.success('已提交取消请求')
    pollTimer = window.setTimeout(() => void pollRun(run.id), 300)
  } catch (caught) {
    toast.error(getErrorMessage(caught))
  }
}

onMounted(() => void load())
onBeforeUnmount(stopPolling)
</script>

<template>
  <div class="page">
    <PageHeader
      title="RAG 评测"
      description="使用固定 Collection 执行真实 retrieval 或可选 rag 评测"
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
          variant="primary"
          :disabled="loading || knowledgeBaseStore.items.length === 0"
          @click="openCreate"
        >
          <Plus :size="14" />
          新建运行
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
        <div class="metrics-grid evaluation-metrics">
          <MetricCard v-for="card in metricCards" :key="card.label" v-bind="card" />
        </div>

        <div class="evaluation-layout">
          <section class="card">
            <div class="toolbar">
              <div>
                <h2 class="card-title">评测历史</h2>
                <p class="card-description">进度、阶段和错误均来自持久化 Job</p>
              </div>
              <label class="search-field">
                <Search :size="14" />
                <span class="sr-only">搜索评测运行</span>
                <input v-model="search" class="input" placeholder="搜索运行或数据集" />
              </label>
            </div>
            <EmptyState
              v-if="filteredRuns.length === 0"
              title="暂无评测运行"
              description="上传或选择 JSONL 数据集后直接提交运行。"
            />
            <div v-else class="table-scroll">
              <table class="data-table evaluation-table">
                <thead>
                  <tr>
                    <th>运行</th>
                    <th>模式</th>
                    <th>状态</th>
                    <th>案例</th>
                    <th>阶段</th>
                    <th>创建时间</th>
                    <th style="text-align: right">操作</th>
                  </tr>
                </thead>
                <tbody>
                  <tr
                    v-for="run in filteredRuns"
                    :key="run.id"
                    :class="{ 'is-selected': selectedRun?.id === run.id }"
                    @click="selectRun(run)"
                  >
                    <td>
                      <div class="table-primary">{{ run.name }}</div>
                      <div class="table-subcopy">
                        {{ run.dataset?.name ?? '已删除数据集' }} ·
                        {{ run.knowledgeBaseName }}
                      </div>
                      <div
                        v-if="
                          ['QUEUED', 'RUNNING', 'CANCEL_REQUESTED'].includes(run.status)
                        "
                        class="progress evaluation-progress"
                      >
                        <div
                          class="progress-bar"
                          :style="{ width: `${run.progress}%` }"
                        />
                      </div>
                    </td>
                    <td>{{ run.mode }}</td>
                    <td><StatusBadge :status="run.outcome ?? run.status" /></td>
                    <td>{{ run.dataset?.caseCount ?? '—' }}</td>
                    <td>{{ run.stage ?? '—' }}</td>
                    <td>{{ formatDateTime(run.createdAt) }}</td>
                    <td>
                      <div class="table-actions">
                        <AppButton
                          v-if="
                            ['QUEUED', 'RUNNING', 'CANCEL_REQUESTED'].includes(
                              run.status,
                            )
                          "
                          size="sm"
                          :disabled="run.status === 'CANCEL_REQUESTED'"
                          @click.stop="cancelRun(run)"
                        >
                          <Square :size="12" />
                          请求取消
                        </AppButton>
                      </div>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </section>

          <section class="card evaluation-detail">
            <div class="card-header">
              <div>
                <h2 class="card-title">报告与案例</h2>
                <p class="card-description">
                  null 指标表示数据集未提供可计算的 source_ids
                </p>
              </div>
              <label v-if="selectedRun?.status === 'SUCCEEDED'">
                <input
                  v-model="failedOnly"
                  type="checkbox"
                  @change="toggleFailedOnly"
                />
                仅失败案例
              </label>
            </div>
            <EmptyState
              v-if="selectedRun === null"
              title="选择一项运行"
              description="从左侧选择真实评测历史。"
            />
            <template v-else>
              <p v-if="selectedRun.errorMessage" class="form-error">
                {{ selectedRun.errorCode }}：{{ selectedRun.errorMessage }}
              </p>
              <div v-if="selectedRetrievalMetrics" class="system-info-grid">
                <div
                  v-for="(value, key) in selectedRetrievalMetrics"
                  :key="key"
                  class="info-tile"
                >
                  <div class="info-label">{{ key }}</div>
                  <div class="info-value">
                    {{ value === null ? '—' : String(value) }}
                  </div>
                </div>
              </div>
              <LoadingState v-if="casesLoading" />
              <EmptyState
                v-else-if="cases.length === 0"
                title="暂无案例结果"
                description="运行尚未完成，或当前失败过滤下没有案例。"
              />
              <div v-else class="evaluation-detail-body">
                <select
                  v-model.number="selectedCaseIndex"
                  class="native-select"
                  aria-label="选择评测案例"
                >
                  <option v-for="item in cases" :key="item.index" :value="item.index">
                    #{{ item.index + 1 }} {{ item.question }}
                  </option>
                </select>
                <template v-if="selectedCase">
                  <div class="question-card">
                    <div class="question-label">问题</div>
                    <div class="question-copy">{{ selectedCase.question }}</div>
                  </div>
                  <div class="question-card">
                    <div class="question-label">期望答案要点</div>
                    <div class="question-copy">
                      {{ selectedCase.expectedAnswers.join('；') }}
                    </div>
                  </div>
                  <div v-if="selectedRun.mode === 'rag'" class="question-card">
                    <div class="question-label">模型回答</div>
                    <div class="question-copy">
                      {{ selectedCase.answer ?? '无回答' }}
                    </div>
                  </div>
                  <p v-if="selectedCase.error" class="form-error">
                    {{ selectedCase.error.type }}：{{ selectedCase.error.message }}
                  </p>
                  <div class="score-grid">
                    <div class="summary-tile">
                      <div class="summary-value">{{ selectedCase.sources.length }}</div>
                      <div class="summary-label">来源数</div>
                    </div>
                    <div class="summary-tile">
                      <div class="summary-value">
                        {{
                          formatDuration(
                            (selectedCase.timingSeconds.end_to_end ?? 0) * 1000,
                          )
                        }}
                      </div>
                      <div class="summary-label">端到端耗时</div>
                    </div>
                  </div>
                </template>
              </div>
            </template>
          </section>
        </div>
      </template>
    </div>

    <AppDialog
      v-model:open="createOpen"
      title="新建真实评测运行"
      description="选择已有数据集，或上传并注册新的 JSONL 数据集。"
    >
      <label class="form-field">
        <span class="form-label">运行名称</span>
        <input v-model="form.name" class="input" placeholder="例如：检索回归 2026-07" />
      </label>
      <label class="form-field">
        <span class="form-label">知识库</span>
        <select v-model="form.knowledgeBaseId" class="native-select">
          <option
            v-for="item in knowledgeBaseStore.items"
            :key="item.id"
            :value="item.id"
          >
            {{ item.name }}
          </option>
        </select>
      </label>
      <label class="form-field">
        <span class="form-label">已有数据集</span>
        <select v-model="form.datasetId" class="native-select">
          <option value="">上传新数据集</option>
          <option v-for="item in datasets" :key="item.id" :value="item.id">
            {{ item.name }}（{{ item.caseCount }}）
          </option>
        </select>
      </label>
      <label class="form-field">
        <span class="form-label">上传 JSONL（可选，优先于已有选择）</span>
        <input
          class="input"
          type="file"
          accept=".jsonl,application/x-ndjson"
          @change="chooseDatasetFile"
        />
      </label>
      <template v-if="datasetFile">
        <label class="form-field">
          <span class="form-label">新数据集名称</span>
          <input v-model="form.datasetName" class="input" />
        </label>
        <label class="form-field">
          <span class="form-label">说明</span>
          <input v-model="form.datasetDescription" class="input" />
        </label>
      </template>
      <div class="form-grid">
        <label class="form-field">
          <span class="form-label">模式</span>
          <select v-model="form.mode" class="native-select">
            <option value="retrieval">retrieval</option>
            <option value="rag">rag</option>
          </select>
        </label>
        <label class="form-field">
          <span class="form-label">Top K</span>
          <input
            v-model.number="form.topK"
            class="input"
            type="number"
            min="1"
            max="100"
          />
        </label>
      </div>
      <p v-if="form.mode === 'rag'" class="card-description">
        RAG 模式要求服务器已配置 Chat 模型与 Key；不会降级为 retrieval。
      </p>
      <p v-if="formError" class="form-error" role="alert">{{ formError }}</p>
      <template #footer>
        <AppButton @click="createOpen = false">取消</AppButton>
        <AppButton variant="primary" :loading="submitting" @click="createRun">
          提交运行
        </AppButton>
      </template>
    </AppDialog>
  </div>
</template>
