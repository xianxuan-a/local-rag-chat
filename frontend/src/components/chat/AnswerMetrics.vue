<script setup lang="ts">
import type { AnswerMetrics } from '@/types'
import { formatDuration, formatTokenCount } from '@/utils/format'

defineProps<{
  metrics: AnswerMetrics
}>()
</script>

<template>
  <div class="answer-metrics" aria-label="本轮回答指标">
    <div class="answer-metric">
      <div class="answer-metric-value">
        {{ formatDuration(metrics.retrievalMs) }}
      </div>
      <div class="answer-metric-label">检索耗时</div>
    </div>
    <div class="answer-metric">
      <div class="answer-metric-value">
        {{ formatDuration(metrics.generationMs) }}
      </div>
      <div class="answer-metric-label">生成耗时</div>
    </div>
    <div class="answer-metric">
      <div class="answer-metric-value">
        {{ formatDuration(metrics.totalMs) }}
      </div>
      <div class="answer-metric-label">总耗时</div>
    </div>
    <div class="answer-metric">
      <div class="answer-metric-value">
        {{ formatTokenCount(metrics.promptTokens) }}
      </div>
      <div class="answer-metric-label">Prompt Tokens</div>
    </div>
    <div class="answer-metric">
      <div class="answer-metric-value">
        {{ formatTokenCount(metrics.completionTokens) }}
      </div>
      <div class="answer-metric-label">Completion Tokens</div>
    </div>
  </div>
</template>
