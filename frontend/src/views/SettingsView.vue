<script setup lang="ts">
import { Bot, Check, Database, RotateCcw, Save, Search } from 'lucide-vue-next'
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { toast } from 'vue-sonner'

import { apiConfig } from '@/api/client'
import ErrorState from '@/components/common/ErrorState.vue'
import LoadingState from '@/components/common/LoadingState.vue'
import PageHeader from '@/components/common/PageHeader.vue'
import AppButton from '@/components/ui/AppButton.vue'
import AppSwitch from '@/components/ui/AppSwitch.vue'
import { useSettingsStore } from '@/stores/settings'
import { useAuthStore } from '@/stores/auth'
import type { AppSettings, RetrievalMode } from '@/types'
import { getErrorDetail, getErrorMessage, isCancellationError } from '@/utils/error'
import { formatDateTime } from '@/utils/format'

const settingsStore = useSettingsStore()
const authStore = useAuthStore()
const error = ref<unknown>(null)
const validationErrors = ref<Record<string, string>>({})
const controller = new AbortController()

interface SettingsDraft {
  chatModel: string
  topK: number
  thresholdEnabled: boolean
  scoreThreshold: number
  maxContextCharacters: number
  webSearchEnabled: boolean
  defaultRetrievalMode: RetrievalMode
  minimumEvidenceCount: number
  freshnessTerms: string
}

const draft = reactive<SettingsDraft>({
  chatModel: '',
  topK: 5,
  thresholdEnabled: false,
  scoreThreshold: 0.72,
  maxContextCharacters: 12_000,
  webSearchEnabled: false,
  defaultRetrievalMode: 'knowledge_first',
  minimumEvidenceCount: 1,
  freshnessTerms: '',
})

const settings = computed(() => settingsStore.settings)
function replaceDraft(value: AppSettings): void {
  draft.chatModel = value.chatModel ?? ''
  draft.topK = value.topK
  draft.thresholdEnabled = value.scoreThreshold !== null
  draft.scoreThreshold = value.scoreThreshold ?? 0.72
  draft.maxContextCharacters = value.maxContextCharacters
  draft.webSearchEnabled = value.webSearchEnabled
  draft.defaultRetrievalMode = value.defaultRetrievalMode
  draft.minimumEvidenceCount = value.minimumEvidenceCount
  draft.freshnessTerms = value.freshnessTerms.join(', ')
  validationErrors.value = {}
}

function validate(): boolean {
  const errors: Record<string, string> = {}
  if (draft.chatModel.length > 100)
    errors.chatModel = 'Chat 模型标识不能超过 100 个字符。'
  if (!Number.isInteger(draft.topK) || draft.topK < 1 || draft.topK > 100) {
    errors.topK = '默认 TopK 必须是 1–100 的整数。'
  }
  if (
    draft.thresholdEnabled &&
    (!Number.isFinite(draft.scoreThreshold) ||
      draft.scoreThreshold < -1 ||
      draft.scoreThreshold > 1)
  ) {
    errors.scoreThreshold = '检索阈值必须在 -1–1 之间。'
  }
  if (
    !Number.isInteger(draft.minimumEvidenceCount) ||
    draft.minimumEvidenceCount < 1 ||
    draft.minimumEvidenceCount > 100
  ) {
    errors.minimumEvidenceCount = '最小证据数必须是 1–100 的整数。'
  }
  const freshnessTerms = draft.freshnessTerms
    .split(',')
    .map((term) => term.trim())
    .filter(Boolean)
  if (
    freshnessTerms.length < 1 ||
    freshnessTerms.length > 64 ||
    freshnessTerms.some((term) => term.length > 64)
  ) {
    errors.freshnessTerms = '请提供 1–64 个逗号分隔的时效词。'
  }
  if (
    !Number.isInteger(draft.maxContextCharacters) ||
    draft.maxContextCharacters < 1_000 ||
    draft.maxContextCharacters > 1_000_000
  ) {
    errors.maxContextCharacters = '上下文字符预算必须是 1,000–1,000,000 的整数。'
  }
  validationErrors.value = errors
  return Object.keys(errors).length === 0
}

async function load(force = false): Promise<void> {
  error.value = null
  try {
    const value = await settingsStore.load(force, controller.signal)
    replaceDraft(value)
  } catch (caught) {
    if (!isCancellationError(caught)) error.value = caught
  }
}

async function save(): Promise<void> {
  if (!validate()) {
    toast.error('设置校验失败')
    return
  }
  try {
    const value = await settingsStore.save({
      chatModel: draft.chatModel.trim() || null,
      topK: draft.topK,
      scoreThreshold: draft.thresholdEnabled ? draft.scoreThreshold : null,
      maxContextCharacters: draft.maxContextCharacters,
      webSearchEnabled: draft.webSearchEnabled,
      defaultRetrievalMode: draft.defaultRetrievalMode,
      minimumEvidenceCount: draft.minimumEvidenceCount,
      freshnessTerms: draft.freshnessTerms
        .split(',')
        .map((term) => term.trim())
        .filter(Boolean),
    })
    replaceDraft(value)
    toast.success('服务器设置已保存并重新读取')
  } catch (caught) {
    const detail = getErrorDetail(caught)
    if (detail) toast.error(getErrorMessage(caught), { description: detail })
    else toast.error(getErrorMessage(caught))
  }
}

function discard(): void {
  if (settings.value !== null) replaceDraft(settings.value)
  toast('已撤销未保存修改')
}

onMounted(() => void load())
onBeforeUnmount(() => controller.abort())
</script>

<template>
  <div class="page">
    <PageHeader title="系统设置" description="管理服务器持久化的安全业务参数">
      <template v-if="authStore.isAdmin" #actions>
        <AppButton :disabled="settings === null" @click="discard">
          <RotateCcw :size="14" aria-hidden="true" />
          撤销未保存修改
        </AppButton>
        <AppButton
          variant="primary"
          :loading="settingsStore.saving"
          :disabled="settings === null"
          @click="save"
        >
          <Save :size="14" aria-hidden="true" />
          保存设置
        </AppButton>
      </template>
    </PageHeader>

    <div class="page-content">
      <LoadingState v-if="settingsStore.loading && settings === null" />
      <ErrorState
        v-else-if="error"
        :message="getErrorMessage(error)"
        :detail="getErrorDetail(error)"
        @retry="load(true)"
      />
      <template v-else-if="settings">
        <div class="settings-grid">
          <section class="card">
            <div class="card-header">
              <div>
                <h2 class="card-title">模型配置</h2>
                <p class="card-description">Secret 仍只由服务器环境变量提供</p>
              </div>
              <Bot :size="17" aria-hidden="true" />
            </div>
            <div class="settings-body">
              <div class="settings-row">
                <div>
                  <div class="settings-label">Chat 模型</div>
                  <div class="settings-note">留空表示生成模型未配置</div>
                </div>
                <label>
                  <span class="sr-only">Chat 模型</span>
                  <input v-model="draft.chatModel" class="input" />
                  <span v-if="validationErrors.chatModel" class="form-error">
                    {{ validationErrors.chatModel }}
                  </span>
                </label>
              </div>
              <div class="settings-row">
                <div>
                  <div class="settings-label">全局联网开关</div>
                  <div class="settings-note">关闭时在线模式会降级为仅知识库</div>
                </div>
                <AppSwitch v-model="draft.webSearchEnabled" label="启用联网检索" />
              </div>
              <div class="settings-row">
                <div>
                  <div class="settings-label">默认检索模式</div>
                  <div class="settings-note">新会话输入框的服务器默认值</div>
                </div>
                <select
                  v-model="draft.defaultRetrievalMode"
                  class="native-select"
                  aria-label="默认检索模式"
                >
                  <option value="knowledge_only">仅知识库</option>
                  <option value="knowledge_first">知识库优先</option>
                  <option value="hybrid">混合检索</option>
                </select>
              </div>
              <div class="settings-row">
                <div>
                  <div class="settings-label">最小证据数</div>
                  <div class="settings-note">知识库优先模式的确定性判定条件</div>
                </div>
                <label>
                  <input
                    v-model.number="draft.minimumEvidenceCount"
                    class="input"
                    type="number"
                    min="1"
                    max="100"
                    aria-label="最小证据数"
                  />
                  <span v-if="validationErrors.minimumEvidenceCount" class="form-error">
                    {{ validationErrors.minimumEvidenceCount }}
                  </span>
                </label>
              </div>
              <div class="settings-row">
                <div>
                  <div class="settings-label">时效词</div>
                  <div class="settings-note">用逗号分隔，命中时触发联网判定</div>
                </div>
                <label>
                  <input
                    v-model="draft.freshnessTerms"
                    class="input"
                    aria-label="时效词"
                  />
                  <span v-if="validationErrors.freshnessTerms" class="form-error">
                    {{ validationErrors.freshnessTerms }}
                  </span>
                </label>
              </div>
              <div class="settings-row">
                <div>
                  <div class="settings-label">联网 Provider</div>
                  <div class="settings-note">密钥不会返回浏览器</div>
                </div>
                <span class="badge badge-light">
                  {{ settings.webSearchProvider }} ·
                  {{ settings.webSearchProviderConfigured ? '已配置' : '未配置' }}
                </span>
              </div>
              <div class="settings-row">
                <div>
                  <div class="settings-label">Embedding</div>
                  <div class="settings-note">向量空间参数只读，修改需走重建流程</div>
                </div>
                <div class="mono">
                  {{ settings.embeddingProvider }} / {{ settings.embeddingModel }} /
                  {{ settings.embeddingDimension }}D / {{ settings.vectorMetric }}
                </div>
              </div>
              <div class="settings-row">
                <div>
                  <div class="settings-label">DashScope API Key</div>
                  <div class="settings-note">密钥不会返回浏览器或写入设置表</div>
                </div>
                <span class="badge badge-light">
                  {{ settings.apiKeyConfigured ? '已配置' : '未配置' }}
                </span>
              </div>
            </div>
          </section>

          <section class="card">
            <div class="card-header">
              <div>
                <h2 class="card-title">检索配置</h2>
                <p class="card-description">检索页可在单次请求中覆盖默认值</p>
              </div>
              <Search :size="17" aria-hidden="true" />
            </div>
            <div class="settings-body">
              <div class="settings-row">
                <div>
                  <div class="settings-label">默认 TopK</div>
                  <div class="settings-note">允许 1–100</div>
                </div>
                <label>
                  <input
                    v-model.number="draft.topK"
                    class="input"
                    type="number"
                    aria-label="默认 TopK"
                    min="1"
                    max="100"
                  />
                  <span v-if="validationErrors.topK" class="form-error">
                    {{ validationErrors.topK }}
                  </span>
                </label>
              </div>
              <div class="settings-row">
                <div>
                  <div class="settings-label">启用默认分数阈值</div>
                  <div class="settings-note">关闭时由后端返回 TopK 内全部候选</div>
                </div>
                <AppSwitch v-model="draft.thresholdEnabled" label="启用默认分数阈值" />
              </div>
              <div v-if="draft.thresholdEnabled" class="settings-row">
                <div>
                  <div class="settings-label">默认分数阈值</div>
                  <div class="settings-note">允许 -1–1</div>
                </div>
                <label>
                  <input
                    v-model.number="draft.scoreThreshold"
                    class="input"
                    type="number"
                    aria-label="默认分数阈值"
                    min="-1"
                    max="1"
                    step="0.01"
                  />
                  <span v-if="validationErrors.scoreThreshold" class="form-error">
                    {{ validationErrors.scoreThreshold }}
                  </span>
                </label>
              </div>
              <div class="settings-row">
                <div>
                  <div class="settings-label">最大上下文字符数</div>
                  <div class="settings-note">生成回答使用的字符预算</div>
                </div>
                <label>
                  <input
                    v-model.number="draft.maxContextCharacters"
                    class="input"
                    type="number"
                    aria-label="最大上下文字符数"
                    min="1000"
                    max="1000000"
                    step="1000"
                  />
                  <span v-if="validationErrors.maxContextCharacters" class="form-error">
                    {{ validationErrors.maxContextCharacters }}
                  </span>
                </label>
              </div>
            </div>
          </section>
        </div>

        <section class="card system-info" style="margin-top: 14px">
          <div class="card-header">
            <div>
              <h2 class="card-title">有效配置来源</h2>
              <p class="card-description">环境默认值可由数据库中的安全业务配置覆盖</p>
            </div>
            <Database :size="17" aria-hidden="true" />
          </div>
          <div class="card-body">
            <div class="system-info-grid">
              <div class="info-tile">
                <div class="info-label">前端模式</div>
                <div class="info-value">
                  {{ apiConfig.mode === 'real' ? 'Real' : 'Mock' }}
                </div>
              </div>
              <div class="info-tile">
                <div class="info-label">服务器来源</div>
                <div class="info-value">
                  {{
                    settings.source === 'persistent'
                      ? '数据库持久化'
                      : settings.source === 'mock'
                        ? 'Mock'
                        : '环境默认值'
                  }}
                </div>
              </div>
              <div class="info-tile">
                <div class="info-label">最近保存</div>
                <div class="info-value">
                  {{
                    settings.updatedAt
                      ? formatDateTime(settings.updatedAt)
                      : '尚无持久化记录'
                  }}
                </div>
              </div>
            </div>
            <div class="settings-runtime-note">
              <Check :size="16" aria-hidden="true" />
              <div>
                <strong>服务器状态为唯一事实来源</strong>
                <p>
                  保存成功后页面会再次读取服务器；浏览器不会保存密钥或业务配置副本。
                </p>
              </div>
            </div>
          </div>
        </section>
      </template>
    </div>
  </div>
</template>
