<script setup lang="ts">
import {
  Bot,
  Copy,
  LoaderCircle,
  RefreshCw,
  TriangleAlert,
  User,
} from 'lucide-vue-next'

import AnswerFeedback from '@/components/chat/AnswerFeedback.vue'
import AnswerMetrics from '@/components/chat/AnswerMetrics.vue'
import MarkdownContent from '@/components/common/MarkdownContent.vue'
import AppButton from '@/components/ui/AppButton.vue'
import AppTooltip from '@/components/ui/AppTooltip.vue'
import type {
  AnswerFeedback as AnswerFeedbackValue,
  ChatMessage,
  SourceReference,
} from '@/types'

defineProps<{
  message: ChatMessage
  actionDisabled?: boolean
}>()

const emit = defineEmits<{
  copy: [message: ChatMessage]
  retry: [message: ChatMessage]
  regenerate: [message: ChatMessage]
  feedback: [message: ChatMessage, feedback: AnswerFeedbackValue]
  source: [source: SourceReference]
}>()

function failureTitle(errorCode: string | null | undefined): string {
  const titles: Record<string, string> = {
    NO_ACTIVE_INDEX: '知识库没有活动索引',
    MODEL_TIMEOUT: '模型响应超时',
    MODEL_UNAVAILABLE: '模型服务不可用',
    CITATION_INVALID: '模型返回了越界引用',
    CHAT_CONFLICT: '当前会话正在处理其他请求',
    CHAT_RESOURCE_NOT_FOUND: '会话或知识库不存在',
    CHAT_VALIDATION_ERROR: '问答参数校验失败',
    CHAT_REQUEST_FAILED: '问答请求被服务端拒绝',
    CHAT_INTERNAL_ERROR: '问答服务内部错误',
    CLIENT_CANCELLED: '本次回答已由用户停止',
    CLIENT_DISCONNECTED: '客户端连接已中断',
    ORPHANED_STREAMING_MESSAGE: '服务重启后流式回答已终止',
  }
  if (!errorCode) return '服务端未提供错误分类'
  return titles[errorCode] ?? `未识别的问答错误：${errorCode}`
}

function modeLabel(mode: ChatMessage['effectiveMode']): string {
  return {
    knowledge_only: '仅知识库',
    knowledge_first: '知识库优先',
    hybrid: '混合检索',
  }[mode]
}
</script>

<template>
  <article
    class="message"
    :class="{ 'message-user': message.role === 'user' }"
    :aria-label="message.role === 'user' ? '用户消息' : 'AI 回答'"
  >
    <span class="message-avatar">
      <User v-if="message.role === 'user'" :size="14" aria-hidden="true" />
      <Bot v-else :size="14" aria-hidden="true" />
    </span>
    <div class="message-content">
      <div class="message-bubble">
        <template v-if="message.status === 'failed'">
          <div style="display: flex; align-items: center; gap: 7px; font-weight: 700">
            <TriangleAlert :size="15" aria-hidden="true" />
            {{ failureTitle(message.errorCode) }}
          </div>
          <p style="margin: 7px 0 0; color: var(--text-secondary)">
            {{ message.errorMessage }}
          </p>
          <span
            v-if="message.errorCode"
            class="badge badge-light"
            style="margin-top: 9px"
          >
            {{ message.errorCode }}
          </span>
          <MarkdownContent
            v-if="message.content"
            :content="message.content"
            style="margin-top: 10px"
          />
        </template>
        <template v-else-if="message.role === 'assistant'">
          <MarkdownContent :content="message.content" />
          <div class="compact-meta" style="margin-top: 9px">
            实际模式：{{ modeLabel(message.effectiveMode) }}
            <template v-if="message.requestedMode !== message.effectiveMode">
              · 请求 {{ modeLabel(message.requestedMode) }}
            </template>
            · 联网 {{ message.webSearchStatus }} · 本地
            {{ message.knowledgeSourceCount }} · 网页 {{ message.webSourceCount }}
          </div>
          <div
            v-if="message.fallbackReason"
            class="compact-meta"
            style="margin-top: 4px"
          >
            降级原因：{{ message.fallbackReason }}
          </div>
          <span
            v-if="message.status === 'streaming'"
            style="display: inline-flex; margin-left: 4px"
            aria-live="polite"
          >
            <LoaderCircle :size="12" class="spin" aria-hidden="true" />
            <span class="sr-only">回答生成中</span>
          </span>
          <div v-if="message.sources.length" style="margin-top: 10px">
            <button
              v-for="source in message.sources"
              :key="source.reference"
              type="button"
              class="source-ref"
              :aria-label="`查看来源 ${source.citationNumber}`"
              @click="emit('source', source)"
            >
              {{ source.reference }}
            </button>
          </div>
          <AnswerMetrics v-if="message.metrics" :metrics="message.metrics" />
        </template>
        <template v-else>
          {{ message.content }}
        </template>
      </div>

      <div v-if="message.role === 'assistant'" class="message-actions">
        <AppTooltip text="复制回答">
          <AppButton
            size="icon"
            variant="ghost"
            aria-label="复制回答"
            :disabled="actionDisabled || message.status === 'streaming'"
            @click="emit('copy', message)"
          >
            <Copy :size="12" aria-hidden="true" />
          </AppButton>
        </AppTooltip>
        <AppTooltip :text="message.status === 'failed' ? '重试回答' : '重新生成'">
          <AppButton
            size="icon"
            variant="ghost"
            :aria-label="message.status === 'failed' ? '重试回答' : '重新生成'"
            :disabled="actionDisabled || message.status === 'streaming'"
            @click="
              message.status === 'failed'
                ? emit('retry', message)
                : emit('regenerate', message)
            "
          >
            <RefreshCw :size="12" aria-hidden="true" />
          </AppButton>
        </AppTooltip>
        <AnswerFeedback
          v-if="message.status === 'complete'"
          :feedback="message.feedback"
          :disabled="actionDisabled"
          @change="emit('feedback', message, $event)"
        />
        <span v-if="message.status === 'cancelled'" class="message-metrics-inline">
          已停止生成
        </span>
      </div>
    </div>
  </article>
</template>
