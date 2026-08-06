<script setup lang="ts">
import { RotateCcw, TriangleAlert } from 'lucide-vue-next'

import AppButton from '@/components/ui/AppButton.vue'

defineProps<{
  title?: string
  message: string
  detail?: string | null
}>()

defineEmits<{
  retry: []
}>()
</script>

<template>
  <div class="card state-view" role="alert">
    <div class="state-icon">
      <TriangleAlert :size="20" aria-hidden="true" />
    </div>
    <div class="state-title">{{ title ?? '加载失败' }}</div>
    <div class="state-copy">{{ message }}</div>
    <details v-if="detail" style="margin-top: 10px; max-width: 520px">
      <summary class="muted" style="cursor: pointer; font-size: 9px">
        查看技术详情
      </summary>
      <pre class="json-view" style="margin-top: 8px">{{ detail }}</pre>
    </details>
    <div class="state-actions">
      <AppButton @click="$emit('retry')">
        <RotateCcw :size="14" aria-hidden="true" />
        重试
      </AppButton>
    </div>
  </div>
</template>
