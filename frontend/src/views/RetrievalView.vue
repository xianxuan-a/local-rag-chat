<script setup lang="ts">
import { Braces, Play, Search } from 'lucide-vue-next'
import { onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'

import { retrievalApi } from '@/api/retrievalApi'
import EmptyState from '@/components/common/EmptyState.vue'
import ErrorState from '@/components/common/ErrorState.vue'
import PageHeader from '@/components/common/PageHeader.vue'
import AppButton from '@/components/ui/AppButton.vue'
import AppSwitch from '@/components/ui/AppSwitch.vue'
import { useKnowledgeBaseStore } from '@/stores/knowledgeBase'
import { useSettingsStore } from '@/stores/settings'
import type { RetrievalRequest, RetrievalResponse } from '@/types'
import { getErrorDetail, getErrorMessage, isCancellationError } from '@/utils/error'
import { formatScore } from '@/utils/format'

const knowledgeBaseStore = useKnowledgeBaseStore()
const settingsStore = useSettingsStore()
const form = reactive({
  knowledgeBaseId: '',
  query: '',
  topK: 5,
  thresholdEnabled: false,
  scoreThreshold: 0.72,
})
const response = ref<RetrievalResponse | null>(null)
const loading = ref(false)
const error = ref<unknown>(null)
const showJson = ref(false)
let controller: AbortController | null = null
let requestVersion = 0

async function execute(): Promise<void> {
  if (!form.knowledgeBaseId || !form.query.trim()) return
  controller?.abort()
  const currentController = new AbortController()
  controller = currentController
  const version = ++requestVersion
  loading.value = true
  error.value = null
  try {
    const request: RetrievalRequest = {
      knowledgeBaseId: form.knowledgeBaseId,
      query: form.query.trim(),
      topK: form.topK,
      scoreThreshold: form.thresholdEnabled ? form.scoreThreshold : null,
    }
    const result = await retrievalApi.execute(request, {
      signal: currentController.signal,
    })
    if (version === requestVersion) response.value = result
  } catch (caught) {
    if (!isCancellationError(caught) && version === requestVersion) {
      error.value = caught
      response.value = null
    }
  } finally {
    if (version === requestVersion) loading.value = false
  }
}

function metadataText(
  metadata: RetrievalResponse['results'][number]['metadata'],
): string {
  return Object.entries(metadata)
    .map(([key, value]) => `${key}=${String(value)}`)
    .join(' · ')
}

onMounted(async () => {
  try {
    await Promise.all([knowledgeBaseStore.load(), settingsStore.load()])
    form.knowledgeBaseId = knowledgeBaseStore.currentId
    const settings = settingsStore.settings
    if (settings !== null) {
      form.topK = settings.topK
      form.thresholdEnabled = settings.scoreThreshold !== null
      form.scoreThreshold = settings.scoreThreshold ?? 0.72
    }
  } catch (caught) {
    error.value = caught
  }
})

watch(
  () => knowledgeBaseStore.currentId,
  (value) => {
    if (value) form.knowledgeBaseId = value
  },
)

watch(
  () => [
    form.knowledgeBaseId,
    form.query,
    form.topK,
    form.thresholdEnabled,
    form.scoreThreshold,
  ],
  () => {
    if (!loading.value) return
    controller?.abort()
    requestVersion += 1
    loading.value = false
  },
)

onBeforeUnmount(() => controller?.abort())
</script>

<template>
  <div class="page">
    <PageHeader title="检索测试" description="使用服务器活动索引执行真实向量检索">
      <template #actions>
        <AppButton
          variant="primary"
          :loading="loading"
          :disabled="!form.knowledgeBaseId || !form.query.trim()"
          @click="execute"
        >
          <Play :size="14" aria-hidden="true" />
          执行检索
        </AppButton>
      </template>
    </PageHeader>

    <div class="page-content">
      <div class="retrieval-layout">
        <section class="card">
          <div class="card-header">
            <div>
              <div class="card-title">检索参数</div>
              <div class="card-description">参数将直接传入 RetrievalService</div>
            </div>
            <Search :size="15" class="muted" aria-hidden="true" />
          </div>
          <div class="card-body parameter-form">
            <div class="form-field">
              <label class="form-label" for="retrieval-kb">知识库</label>
              <select
                id="retrieval-kb"
                v-model="form.knowledgeBaseId"
                class="native-select"
              >
                <option value="" disabled>请选择知识库</option>
                <option
                  v-for="item in knowledgeBaseStore.items"
                  :key="item.id"
                  :value="item.id"
                >
                  {{ item.name }}
                </option>
              </select>
            </div>
            <div class="form-field">
              <label class="form-label" for="retrieval-query">查询文本</label>
              <textarea
                id="retrieval-query"
                v-model="form.query"
                class="textarea"
                maxlength="4000"
                placeholder="输入要在当前知识库中检索的问题"
              />
            </div>
            <div class="form-field">
              <label class="form-label" for="top-k">TopK</label>
              <div class="range-row">
                <input
                  id="top-k"
                  v-model.number="form.topK"
                  type="range"
                  min="1"
                  max="100"
                />
                <input
                  v-model.number="form.topK"
                  class="input"
                  type="number"
                  min="1"
                  max="100"
                />
              </div>
            </div>
            <div class="switch-row">
              <div>
                <div class="form-label">分数阈值</div>
                <div class="form-hint">关闭时发送 null，使用无阈值语义</div>
              </div>
              <AppSwitch v-model="form.thresholdEnabled" label="启用分数阈值" />
            </div>
            <div v-if="form.thresholdEnabled" class="form-field">
              <label class="form-label" for="score-threshold">score threshold</label>
              <div class="range-row">
                <input
                  id="score-threshold"
                  v-model.number="form.scoreThreshold"
                  type="range"
                  min="-1"
                  max="1"
                  step="0.01"
                />
                <input
                  v-model.number="form.scoreThreshold"
                  class="input"
                  type="number"
                  min="-1"
                  max="1"
                  step="0.01"
                />
              </div>
            </div>
            <AppButton
              variant="primary"
              :loading="loading"
              :disabled="!form.knowledgeBaseId || !form.query.trim()"
              @click="execute"
            >
              <Play :size="14" aria-hidden="true" />
              执行检索
            </AppButton>
          </div>
        </section>

        <section class="card">
          <div class="card-header">
            <div>
              <div class="card-title">检索结果</div>
              <div class="card-description">分数、来源和正文均来自服务器</div>
            </div>
            <div class="toolbar-group">
              <span class="badge badge-light">
                {{ response?.resultCount ?? 0 }} results
              </span>
              <AppButton
                size="sm"
                :disabled="response === null"
                @click="showJson = !showJson"
              >
                <Braces :size="13" aria-hidden="true" />
                {{ showJson ? '结果卡片' : 'JSON' }}
              </AppButton>
            </div>
          </div>

          <ErrorState
            v-if="error"
            :message="getErrorMessage(error)"
            :detail="getErrorDetail(error)"
            @retry="execute"
          />
          <template v-else-if="response">
            <div class="result-summary">
              <div class="summary-tile">
                <div class="summary-value">{{ response.queryTimeMs }} ms</div>
                <div class="summary-label">服务器查询耗时</div>
              </div>
              <div class="summary-tile">
                <div class="summary-value">{{ response.resultCount }}</div>
                <div class="summary-label">真实结果数</div>
              </div>
            </div>

            <pre v-if="showJson" class="json-view">{{
              JSON.stringify(response, null, 2)
            }}</pre>
            <EmptyState
              v-else-if="response.results.length === 0"
              title="没有匹配结果"
              description="活动索引可用，但本次查询没有返回满足条件的分块。"
            />
            <div v-else class="retrieval-results">
              <article
                v-for="result in response.results"
                :key="`${result.fileId}:${result.chunkId}`"
                class="retrieval-result"
              >
                <div class="result-rank">{{ result.rank }}</div>
                <div>
                  <div class="result-file">{{ result.fileName }}</div>
                  <div class="result-preview">{{ result.content }}</div>
                  <div class="result-meta">
                    file={{ result.fileId }} · chunk={{ result.chunkId }}
                    <template v-if="metadataText(result.metadata)">
                      · {{ metadataText(result.metadata) }}
                    </template>
                  </div>
                </div>
                <div class="result-score">
                  <div class="score-value">{{ formatScore(result.score) }}</div>
                  <div class="score-label">SCORE</div>
                </div>
              </article>
            </div>
          </template>
          <EmptyState
            v-else
            title="尚未执行检索"
            description="选择知识库、输入查询文本并执行真实检索。"
          />
        </section>
      </div>
    </div>
  </div>
</template>
