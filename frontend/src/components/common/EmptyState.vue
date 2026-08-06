<script setup lang="ts">
import { FolderOpen } from 'lucide-vue-next'

defineProps<{
  title: string
  description: string
}>()
</script>

<template>
  <div class="state-view">
    <div class="state-icon">
      <FolderOpen :size="20" aria-hidden="true" />
    </div>
    <div class="state-title">{{ title }}</div>
    <div class="state-copy">{{ description }}</div>
    <div v-if="$slots.actions" class="state-actions">
      <slot name="actions" />
    </div>
  </div>
</template>
