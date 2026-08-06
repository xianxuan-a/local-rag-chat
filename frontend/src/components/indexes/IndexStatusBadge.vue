<script setup lang="ts">
import StatusBadge from '@/components/common/StatusBadge.vue'
import type { IndexLifecycle } from '@/types'

defineProps<{
  status: IndexLifecycle
}>()
</script>

<template>
  <StatusBadge :status="status" />
</template>
