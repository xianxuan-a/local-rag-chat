<script setup lang="ts">
import StatusBadge from '@/components/common/StatusBadge.vue'
import type { FileStatus } from '@/types'

defineProps<{
  status: FileStatus
}>()
</script>

<template>
  <StatusBadge :status="status" />
</template>
