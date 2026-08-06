<script setup lang="ts">
import {
  Check,
  CircleDashed,
  Clock3,
  LoaderCircle,
  TriangleAlert,
} from 'lucide-vue-next'
import { computed, type Component } from 'vue'

const props = defineProps<{
  status: string
}>()

const normalized = computed(() => props.status.toLowerCase())

const label = computed(() => {
  const labels: Record<string, string> = {
    success: '成功',
    succeeded: '成功',
    queued: '等待中',
    cancel_requested: '取消中',
    processing: '处理中',
    pending: '等待中',
    failed: '失败',
    ready: '就绪',
    building: '构建中',
    empty: '空',
    active: 'Active',
    previous: 'Previous',
    cleanup: 'Cleanup',
    draft: '草稿',
    running: '运行中',
    completed: '已完成',
    pass: '通过',
    review: '复核',
    cancelled: '已取消',
  }
  return labels[normalized.value] ?? props.status
})

const icon = computed<Component>(() => {
  if (
    ['success', 'succeeded', 'ready', 'active', 'completed', 'pass'].includes(
      normalized.value,
    )
  ) {
    return Check
  }
  if (
    ['processing', 'building', 'running', 'cancel_requested'].includes(normalized.value)
  ) {
    return LoaderCircle
  }
  if (['failed'].includes(normalized.value)) return TriangleAlert
  if (['pending', 'queued', 'draft', 'previous'].includes(normalized.value)) {
    return Clock3
  }
  return CircleDashed
})

const tone = computed(() => {
  if (normalized.value === 'failed') return 'badge-failed'
  if (
    ['processing', 'building', 'running', 'cancel_requested', 'active'].includes(
      normalized.value,
    )
  ) {
    return 'badge-medium'
  }
  if (
    ['pending', 'queued', 'empty', 'draft', 'cleanup', 'cancelled'].includes(
      normalized.value,
    )
  ) {
    return 'badge-light'
  }
  return 'badge-strong'
})
</script>

<template>
  <span class="badge" :class="tone" :aria-label="`状态：${label}`">
    <component
      :is="icon"
      :size="11"
      :class="{ spin: ['processing', 'building', 'running'].includes(normalized) }"
      aria-hidden="true"
    />
    {{ label }}
  </span>
</template>
