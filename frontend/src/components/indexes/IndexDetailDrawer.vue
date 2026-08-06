<script setup lang="ts">
import { Layers3 } from 'lucide-vue-next'

import IndexStatusBadge from '@/components/indexes/IndexStatusBadge.vue'
import AppSheet from '@/components/ui/AppSheet.vue'
import type { IndexCollection, KnowledgeBase } from '@/types'
import { formatDateTime, formatNumber } from '@/utils/format'

const props = defineProps<{
  open: boolean
  index: IndexCollection | null
  knowledgeBases: KnowledgeBase[]
}>()

const emit = defineEmits<{
  'update:open': [open: boolean]
}>()

function knowledgeBaseName(knowledgeBaseId: string): string {
  return (
    props.knowledgeBases.find((item) => item.id === knowledgeBaseId)?.name ??
    '未知知识库'
  )
}
</script>

<template>
  <AppSheet
    :open="open"
    title="索引详细配置"
    description="查看 Generation、Embedding 和 Collection 配置"
    @update:open="emit('update:open', $event)"
  >
    <template v-if="index">
      <div style="display: flex; align-items: flex-start; gap: 11px">
        <span class="index-summary-icon">
          <Layers3 :size="16" aria-hidden="true" />
        </span>
        <div style="min-width: 0; flex: 1">
          <h2 class="mono" style="margin: 0; font-size: 12px">
            {{ index.collectionName }}
          </h2>
          <div class="compact-meta">
            {{ knowledgeBaseName(index.knowledgeBaseId) }}
          </div>
        </div>
        <IndexStatusBadge :status="index.lifecycle" />
      </div>
      <div class="separator" style="margin: 18px 0" />
      <div class="system-info-grid" style="grid-template-columns: repeat(2, 1fr)">
        <div class="info-tile">
          <div class="info-label">Generation</div>
          <div class="info-value">{{ index.generation }}</div>
        </div>
        <div class="info-tile">
          <div class="info-label">分块数量</div>
          <div class="info-value">{{ formatNumber(index.chunkCount) }}</div>
        </div>
      </div>
      <div class="separator" style="margin: 18px 0" />
      <dl class="tech-grid">
        <dt class="tech-key">provider</dt>
        <dd class="tech-value">{{ index.config.provider }}</dd>
        <dt class="tech-key">model</dt>
        <dd class="tech-value">{{ index.config.model }}</dd>
        <dt class="tech-key">dimension</dt>
        <dd class="tech-value">{{ index.config.dimension }}</dd>
        <dt class="tech-key">normalization</dt>
        <dd class="tech-value">{{ index.config.normalization }}</dd>
        <dt class="tech-key">metric</dt>
        <dd class="tech-value">{{ index.config.metric }}</dd>
        <dt class="tech-key">config_hash</dt>
        <dd class="tech-value">{{ index.config.configHash }}</dd>
        <dt class="tech-key">generation</dt>
        <dd class="tech-value">{{ index.generation }}</dd>
        <dt class="tech-key">collection_name</dt>
        <dd class="tech-value">{{ index.collectionName }}</dd>
        <dt class="tech-key">created_at</dt>
        <dd class="tech-value">{{ formatDateTime(index.createdAt) }}</dd>
        <dt class="tech-key">lifecycle</dt>
        <dd class="tech-value">{{ index.lifecycle }}</dd>
      </dl>
    </template>
  </AppSheet>
</template>
