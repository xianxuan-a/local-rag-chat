<script setup lang="ts">
import {
  Activity,
  Blocks,
  Database,
  FileText,
  Layers3,
  MessageSquareText,
  MessagesSquare,
  RefreshCw,
} from 'lucide-vue-next'
import { computed, onBeforeUnmount, onMounted, ref, type Component } from 'vue'
import type { EChartsCoreOption } from 'echarts/core'

import { apiConfig } from '@/api/client'
import { dashboardApi } from '@/api/dashboardApi'
import BaseChart from '@/components/common/BaseChart.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import ErrorState from '@/components/common/ErrorState.vue'
import LoadingState from '@/components/common/LoadingState.vue'
import MetricCard from '@/components/common/MetricCard.vue'
import PageHeader from '@/components/common/PageHeader.vue'
import StatusBadge from '@/components/common/StatusBadge.vue'
import AppButton from '@/components/ui/AppButton.vue'
import { useKnowledgeBaseStore } from '@/stores/knowledgeBase'
import type { DashboardMetric, DashboardSnapshot } from '@/types'
import { isAbortError } from '@/utils/abort'
import { getErrorDetail, getErrorMessage } from '@/utils/error'
import { formatDateTime } from '@/utils/format'

const knowledgeBaseStore = useKnowledgeBaseStore()
const snapshot = ref<DashboardSnapshot | null>(null)
const loading = ref(true)
const refreshing = ref(false)
const error = ref<unknown>(null)
const scopeId = ref('')
let requestVersion = 0
let controller: AbortController | null = null

const icons: Record<DashboardMetric['id'], Component> = {
  knowledgeBases: Database,
  files: FileText,
  chunks: Blocks,
  questions: Activity,
  sessions: MessagesSquare,
  activeIndexes: Layers3,
}

const lineOption = computed<EChartsCoreOption>(() => ({
  color: ['#171717', '#525252', '#a3a3a3', '#737373', '#d4d4d4'],
  animationDuration: 320,
  grid: { top: 26, right: 20, bottom: 34, left: 46 },
  tooltip: {
    trigger: 'axis',
    backgroundColor: '#ffffff',
    borderColor: '#d4d4d4',
    textStyle: { color: '#171717', fontSize: 11 },
  },
  xAxis: {
    type: 'category',
    boundaryGap: false,
    data: snapshot.value?.trend.map((item) => item.date) ?? [],
    axisLine: { lineStyle: { color: '#d4d4d4' } },
    axisTick: { show: false },
    axisLabel: { color: '#9a9a9a', fontSize: 9 },
  },
  legend: {
    top: 0,
    right: 14,
    itemWidth: 12,
    itemHeight: 7,
    textStyle: { color: '#666666', fontSize: 9 },
  },
  yAxis: {
    type: 'value',
    splitNumber: 4,
    axisLabel: { color: '#9a9a9a', fontSize: 9 },
    splitLine: { lineStyle: { color: '#ededed' } },
  },
  series: [
    {
      name: '用户问题',
      type: 'line',
      smooth: false,
      symbol: 'circle',
      symbolSize: 7,
      lineStyle: { width: 2, color: '#171717' },
      itemStyle: {
        color: '#ffffff',
        borderColor: '#171717',
        borderWidth: 2,
      },
      data: snapshot.value?.trend.map((item) => item.questions) ?? [],
    },
    {
      name: '上传文件',
      type: 'line',
      symbol: 'circle',
      symbolSize: 5,
      lineStyle: { width: 1.5 },
      data: snapshot.value?.trend.map((item) => item.uploads) ?? [],
    },
    {
      name: '失败文件',
      type: 'line',
      symbol: 'circle',
      symbolSize: 5,
      lineStyle: { width: 1.5 },
      data: snapshot.value?.trend.map((item) => item.failedFiles) ?? [],
    },
    {
      name: '索引操作',
      type: 'line',
      symbol: 'circle',
      symbolSize: 5,
      lineStyle: { width: 1.5 },
      data: snapshot.value?.trend.map((item) => item.indexOperations) ?? [],
    },
    {
      name: '评测运行',
      type: 'line',
      symbol: 'circle',
      symbolSize: 5,
      lineStyle: { width: 1.5 },
      data: snapshot.value?.trend.map((item) => item.evaluationRuns) ?? [],
    },
  ],
}))

const donutOption = computed<EChartsCoreOption>(() => ({
  color: ['#171717', '#525252', '#a3a3a3', '#d4d4d4'],
  tooltip: {
    trigger: 'item',
    backgroundColor: '#ffffff',
    borderColor: '#d4d4d4',
    textStyle: { color: '#171717', fontSize: 11 },
  },
  legend: {
    orient: 'vertical',
    right: 14,
    top: 'center',
    itemWidth: 8,
    itemHeight: 8,
    textStyle: { color: '#666666', fontSize: 9 },
  },
  series: [
    {
      type: 'pie',
      radius: ['48%', '70%'],
      center: ['31%', '52%'],
      avoidLabelOverlap: true,
      label: { show: false },
      itemStyle: {
        borderColor: '#ffffff',
        borderWidth: 2,
      },
      data:
        snapshot.value?.fileStatuses.map((item) => ({
          name: item.status,
          value: item.value,
        })) ?? [],
    },
  ],
}))

const fileTotal = computed(
  () =>
    snapshot.value?.fileStatuses.reduce((total, item) => total + item.value, 0) ?? 0,
)

const trendHasData = computed(
  () =>
    snapshot.value?.trend.some(
      (item) =>
        item.questions +
          item.uploads +
          item.failedFiles +
          item.indexOperations +
          item.evaluationRuns >
        0,
    ) ?? false,
)

const scopeLabel = computed(
  () =>
    knowledgeBaseStore.items.find((item) => item.id === scopeId.value)?.name ??
    '全部可见知识库',
)

const sectionErrorMessages = computed(() =>
  Object.values(snapshot.value?.sectionErrors ?? {}),
)

async function load(isRefresh = false): Promise<void> {
  controller?.abort()
  controller = new AbortController()
  const version = ++requestVersion
  if (isRefresh) refreshing.value = true
  else loading.value = true
  error.value = null
  try {
    await knowledgeBaseStore.load()
    const result = await dashboardApi.getSnapshot({
      ...(scopeId.value ? { knowledgeBaseId: scopeId.value } : {}),
      windowDays: 7,
      recentLimit: 5,
      signal: controller.signal,
    })
    if (version === requestVersion) snapshot.value = result
  } catch (caught) {
    if (version === requestVersion && !isAbortError(caught)) {
      error.value = caught
    }
  } finally {
    if (version === requestVersion) {
      loading.value = false
      refreshing.value = false
    }
  }
}

function onKnowledgeBaseChange(event: Event): void {
  const target = event.target
  if (target instanceof HTMLSelectElement) {
    scopeId.value = target.value
    void load(true)
  }
}

onMounted(() => void load())
onBeforeUnmount(() => controller?.abort())
</script>

<template>
  <div class="page">
    <PageHeader
      title="系统总览"
      description="查看知识库、文件处理与问答服务的关键运行指标"
    >
      <template #actions>
        <label style="min-width: 170px">
          <span class="sr-only">当前知识库</span>
          <select
            class="native-select"
            :value="scopeId"
            @change="onKnowledgeBaseChange"
          >
            <option value="">全部可见知识库</option>
            <option
              v-for="item in knowledgeBaseStore.items"
              :key="item.id"
              :value="item.id"
            >
              {{ item.name }}
            </option>
          </select>
        </label>
        <AppButton :loading="refreshing" @click="load(true)">
          <RefreshCw :size="14" aria-hidden="true" />
          刷新数据
        </AppButton>
      </template>
    </PageHeader>

    <div class="page-content">
      <LoadingState v-if="loading" />
      <ErrorState
        v-else-if="error"
        :message="getErrorMessage(error)"
        :detail="getErrorDetail(error)"
        @retry="load()"
      />
      <template v-else-if="snapshot">
        <div class="metrics-grid">
          <MetricCard
            v-for="metric in snapshot.metrics"
            :key="metric.id"
            :label="metric.label"
            :value="metric.value"
            :note="metric.note"
            :icon="icons[metric.id]"
          />
        </div>
        <section v-if="sectionErrorMessages.length > 0" class="card">
          <div class="card-body">
            <div class="card-title">部分数据暂时不可用</div>
            <div class="card-description">
              {{ sectionErrorMessages.join('；') }}
            </div>
          </div>
        </section>

        <div class="dashboard-charts">
          <section class="card">
            <div class="card-header">
              <div>
                <div class="card-title">最近 7 天真实活动趋势</div>
                <div class="card-description">{{ scopeLabel }} · UTC 按日聚合</div>
              </div>
              <span class="badge badge-light">
                {{ formatDateTime(snapshot.generatedAt) }}
              </span>
            </div>
            <div class="card-body">
              <BaseChart
                v-if="trendHasData"
                :option="lineOption"
                ariaLabel="最近七天真实活动趋势折线图"
              />
              <EmptyState
                v-else
                title="最近 7 天没有活动"
                description="上传、问答、索引和评测均没有可聚合记录。"
              />
            </div>
          </section>
          <section class="card">
            <div class="card-header">
              <div>
                <div class="card-title">文件处理状态分布</div>
                <div class="card-description">共 {{ fileTotal }} 个真实文件记录</div>
              </div>
              <RouterLink class="button button-sm button-ghost" to="/files">
                详情
              </RouterLink>
            </div>
            <div class="card-body">
              <BaseChart
                v-if="fileTotal > 0"
                :option="donutOption"
                ariaLabel="文件处理状态环形图"
              />
              <EmptyState
                v-else
                title="暂无文件"
                description="当前范围还没有上传文件。"
              />
            </div>
          </section>
        </div>

        <div class="dashboard-bottom">
          <section class="card">
            <div class="card-header">
              <div>
                <div class="card-title">最近处理文件</div>
                <div class="card-description">按服务器更新时间倒序</div>
              </div>
              <RouterLink class="button button-sm button-ghost" to="/files">
                查看全部
              </RouterLink>
            </div>
            <div class="compact-list">
              <RouterLink
                v-for="file in snapshot.recentFiles"
                :key="file.id"
                class="compact-row"
                :to="{
                  path: '/files',
                  query: { knowledgeBaseId: file.knowledgeBaseId },
                }"
              >
                <div class="truncate">
                  <div class="compact-title">{{ file.fileName }}</div>
                  <div class="compact-meta">
                    {{ file.knowledgeBaseName }} · {{ file.fileType }} ·
                    {{ file.chunkCount }} chunks
                  </div>
                </div>
                <StatusBadge :status="file.status" />
              </RouterLink>
              <EmptyState
                v-if="snapshot.recentFiles.length === 0"
                title="暂无最近文件"
                description="上传后会在这里显示真实文件状态。"
              />
            </div>
          </section>

          <section class="card">
            <div class="card-header">
              <div>
                <div class="card-title">最近问答</div>
                <div class="card-description">按会话服务器更新时间倒序</div>
              </div>
              <MessageSquareText :size="15" class="muted" aria-hidden="true" />
            </div>
            <div class="compact-list">
              <RouterLink
                v-for="session in snapshot.recentSessions"
                :key="session.id"
                class="compact-row"
                :to="{ path: '/chat', query: { sessionId: session.id } }"
              >
                <div class="truncate">
                  <div class="compact-title">{{ session.title }}</div>
                  <div class="compact-meta">
                    {{ session.knowledgeBaseName }} ·
                    {{ formatDateTime(session.updatedAt) }}
                  </div>
                </div>
                <span class="badge badge-light">{{ session.messageCount }} 条</span>
              </RouterLink>
              <EmptyState
                v-if="snapshot.recentSessions.length === 0"
                title="暂无最近会话"
                description="创建会话并提问后会显示真实历史。"
              />
            </div>
          </section>

          <section class="card">
            <div class="card-header">
              <div>
                <div class="card-title">最近任务与配置</div>
                <div class="card-description">
                  数据来源：{{ apiConfig.mode === 'real' ? 'Real API' : 'Mock' }}
                </div>
              </div>
            </div>
            <div class="compact-list">
              <RouterLink
                v-for="job in snapshot.recentIndexJobs"
                :key="`index-${job.id}`"
                class="compact-row"
                to="/indexes"
              >
                <div class="truncate">
                  <div class="compact-title">索引 · {{ job.knowledgeBaseName }}</div>
                  <div class="compact-meta">
                    {{ job.stage ?? job.jobType }} ·
                    {{ formatDateTime(job.createdAt) }}
                  </div>
                </div>
                <StatusBadge :status="job.status" />
              </RouterLink>
              <RouterLink
                v-for="job in snapshot.recentEvaluations"
                :key="`evaluation-${job.id}`"
                class="compact-row"
                to="/evaluation"
              >
                <div class="truncate">
                  <div class="compact-title">评测 · {{ job.knowledgeBaseName }}</div>
                  <div class="compact-meta">
                    {{ job.stage ?? job.jobType }} ·
                    {{ formatDateTime(job.createdAt) }}
                  </div>
                </div>
                <StatusBadge :status="job.status" />
              </RouterLink>
            </div>
            <div class="card-body status-list">
              <div class="status-row">
                <span class="status-name">
                  <i class="status-dot" />
                  Chat 配置
                </span>
                <strong>
                  {{ snapshot.runtime.chatConfigured ? '已配置' : '未配置' }}
                </strong>
              </div>
              <div class="status-row">
                <span class="status-name">
                  <i class="status-dot" />
                  Embedding Key
                </span>
                <strong>
                  {{ snapshot.runtime.embeddingKeyConfigured ? '已配置' : '未配置' }}
                </strong>
              </div>
            </div>
          </section>
        </div>
      </template>
    </div>
  </div>
</template>
