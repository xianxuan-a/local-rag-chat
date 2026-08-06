<script setup lang="ts">
import type { Component } from 'vue'

import { formatNumber } from '@/utils/format'

defineProps<{
  label: string
  value: number
  note: string
  icon: Component
  formatter?: (value: number) => string
}>()
</script>

<template>
  <section class="card metric-card">
    <div class="metric-top">
      <span class="metric-label">{{ label }}</span>
      <span class="metric-icon">
        <component :is="icon" :size="16" aria-hidden="true" />
      </span>
    </div>
    <div class="metric-value">
      {{ formatter ? formatter(value) : formatNumber(value) }}
    </div>
    <div class="metric-foot">
      <span>{{ note }}</span>
    </div>
  </section>
</template>
