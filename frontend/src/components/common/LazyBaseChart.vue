<script setup lang="ts">
import type { EChartsCoreOption } from 'echarts/core'

import { createAsyncChartComponent } from '@/components/common/asyncChart'

defineProps<{
  option: EChartsCoreOption
  ariaLabel: string
}>()

const AsyncBaseChart = createAsyncChartComponent(() =>
  import('@/components/common/BaseChart.vue').then((module) => module.default),
)
</script>

<template>
  <AsyncBaseChart :option="option" :aria-label="ariaLabel" />
</template>
