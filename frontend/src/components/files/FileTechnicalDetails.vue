<script setup lang="ts">
import type { FileRecord } from '@/types'
import { formatDateTime, formatDuration, formatNumber } from '@/utils/format'

defineProps<{
  file: FileRecord
}>()
</script>

<template>
  <dl class="tech-grid">
    <dt class="tech-key">file_id</dt>
    <dd class="tech-value">{{ file.id }}</dd>
    <dt class="tech-key">knowledge_base_id</dt>
    <dd class="tech-value">{{ file.knowledgeBaseId }}</dd>
    <dt class="tech-key">file_path</dt>
    <dd class="tech-value">{{ file.filePath }}</dd>
    <dt class="tech-key">content_hash</dt>
    <dd class="tech-value">{{ file.contentHash }}</dd>
    <dt class="tech-key">chunk_count</dt>
    <dd class="tech-value">{{ formatNumber(file.chunkCount) }}</dd>
    <dt class="tech-key">has_active_vectors</dt>
    <dd class="tech-value">{{ file.hasActiveVectors }}</dd>
    <dt class="tech-key">active_index_config_hash</dt>
    <dd class="tech-value">{{ file.activeIndexConfigHash ?? '—' }}</dd>
    <dt class="tech-key">last_successful_indexed_at</dt>
    <dd class="tech-value">
      {{
        file.lastSuccessfulIndexedAt
          ? formatDateTime(file.lastSuccessfulIndexedAt)
          : '—'
      }}
    </dd>
    <dt class="tech-key">embedding_provider</dt>
    <dd class="tech-value">{{ file.embeddingProvider }}</dd>
    <dt class="tech-key">embedding_model</dt>
    <dd class="tech-value">{{ file.embeddingModel }}</dd>
    <dt class="tech-key">embedding_dimension</dt>
    <dd class="tech-value">{{ file.embeddingDimension }}</dd>
    <dt class="tech-key">vector_metric</dt>
    <dd class="tech-value">{{ file.vectorMetric }}</dd>
    <dt class="tech-key">collection_name</dt>
    <dd class="tech-value">{{ file.collectionName ?? '—' }}</dd>
    <dt class="tech-key">processing_duration</dt>
    <dd class="tech-value">
      {{ file.processingDuration ? formatDuration(file.processingDuration) : '—' }}
    </dd>
    <dt class="tech-key">error_message</dt>
    <dd class="tech-value">{{ file.errorMessage ?? '—' }}</dd>
  </dl>
</template>
