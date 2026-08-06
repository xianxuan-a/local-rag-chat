<script setup lang="ts">
import { Square } from 'lucide-vue-next'

import StatusBadge from '@/components/common/StatusBadge.vue'
import AppButton from '@/components/ui/AppButton.vue'
import type { RebuildSnapshot } from '@/types'

defineProps<{
  snapshot: RebuildSnapshot
  canStop: boolean
}>()

defineEmits<{
  stop: []
}>()
</script>

<template>
  <div class="rebuild-grid" aria-live="polite">
    <section class="card rebuild-progress-card">
      <div class="rebuild-head">
        <div>
          <div class="card-title">索引重建进度</div>
          <div class="card-description">Generation 构建与原子切换流程</div>
        </div>
        <StatusBadge :status="snapshot.status" />
      </div>
      <div class="progress" :aria-label="`索引重建进度 ${snapshot.progress}%`">
        <div class="progress-bar" :style="{ width: `${snapshot.progress}%` }" />
      </div>
      <div class="rebuild-meta">
        <span>
          已处理 {{ snapshot.processedFiles }} / {{ snapshot.totalFiles }} 个文件
        </span>
        <span>{{ snapshot.progress }}%</span>
      </div>
      <AppButton v-if="canStop" style="margin-top: 14px" @click="$emit('stop')">
        <Square :size="13" aria-hidden="true" />
        终止构建
      </AppButton>
    </section>
    <section class="card">
      <div class="card-header">
        <div>
          <div class="card-title">构建步骤</div>
          <div class="card-description">来自服务端持久化 Job 状态</div>
        </div>
      </div>
      <div class="step-list">
        <div
          v-for="(step, index) in snapshot.steps"
          :key="step"
          class="step"
          :class="{
            'is-done': index < snapshot.stepIndex || snapshot.status === 'completed',
            'is-active': index === snapshot.stepIndex && snapshot.status === 'building',
          }"
        >
          <span class="step-dot" />
          <span>{{ step }}</span>
        </div>
      </div>
    </section>
  </div>
</template>
