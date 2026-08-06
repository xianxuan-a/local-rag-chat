<script setup lang="ts">
import type { SourceReference } from '@/types'
import { formatScore } from '@/utils/format'
import { formatDateTime } from '@/utils/format'

defineProps<{
  source: SourceReference
  index: number
}>()

defineEmits<{
  select: [source: SourceReference]
}>()
</script>

<template>
  <button type="button" class="source-card" @click="$emit('select', source)">
    <div class="source-card-top">
      <span class="source-ref">{{ source.reference || index + 1 }}</span>
      <span>score {{ formatScore(source.score) }}</span>
    </div>
    <div class="source-file">{{ source.title }}</div>
    <div v-if="source.sourceType === 'web'" class="result-meta">
      {{ source.domain }}
      <template v-if="source.publishedAt">
        · 发布 {{ formatDateTime(source.publishedAt) }}
      </template>
      <template v-if="source.accessedAt">
        · 访问 {{ formatDateTime(source.accessedAt) }}
      </template>
    </div>
    <div class="source-preview">{{ source.contentPreview }}</div>
    <div v-if="source.chunkId" class="result-meta">{{ source.chunkId }}</div>
  </button>
</template>
