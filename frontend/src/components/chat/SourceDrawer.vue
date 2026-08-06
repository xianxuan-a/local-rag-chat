<script setup lang="ts">
import { Copy, ExternalLink, FileText, Globe2 } from 'lucide-vue-next'
import { toast } from 'vue-sonner'

import AppButton from '@/components/ui/AppButton.vue'
import AppSheet from '@/components/ui/AppSheet.vue'
import type { SourceReference } from '@/types'
import { formatScore } from '@/utils/format'
import { formatDateTime } from '@/utils/format'

const props = defineProps<{
  open: boolean
  source: SourceReference | null
}>()

const emit = defineEmits<{
  'update:open': [open: boolean]
}>()

async function copyContent(): Promise<void> {
  if (props.source === null) return
  await navigator.clipboard.writeText(
    props.source.content ?? props.source.contentPreview,
  )
  toast.success('分块正文已复制')
}
</script>

<template>
  <AppSheet
    :open="open"
    title="来源详情"
    description="查看命中分块的完整正文与追踪信息"
    @update:open="emit('update:open', $event)"
  >
    <template v-if="source">
      <div style="display: flex; align-items: flex-start; gap: 11px">
        <span class="file-glyph">
          <Globe2 v-if="source.sourceType === 'web'" :size="16" aria-hidden="true" />
          <FileText v-else :size="16" aria-hidden="true" />
        </span>
        <div style="min-width: 0; flex: 1">
          <h2 style="margin: 0; font-size: 13px">{{ source.title }}</h2>
          <div class="compact-meta mono">
            {{ source.sourceType === 'web' ? source.domain : source.chunkId }}
          </div>
        </div>
        <span class="badge badge-strong">
          {{ formatScore(source.score) }}
        </span>
      </div>
      <div class="separator" style="margin: 18px 0" />
      <dl v-if="source.sourceType === 'knowledge_base'" class="tech-grid">
        <dt class="tech-key">file_id</dt>
        <dd class="tech-value">{{ source.fileId }}</dd>
        <dt class="tech-key">chunk_id</dt>
        <dd class="tech-value">{{ source.chunkId }}</dd>
        <dt class="tech-key">similarity</dt>
        <dd class="tech-value">{{ formatScore(source.score) }}</dd>
      </dl>
      <dl v-else class="tech-grid">
        <dt class="tech-key">reference</dt>
        <dd class="tech-value">{{ source.reference }}</dd>
        <dt class="tech-key">domain</dt>
        <dd class="tech-value">{{ source.domain }}</dd>
        <dt class="tech-key">published_at</dt>
        <dd class="tech-value">
          {{ source.publishedAt ? formatDateTime(source.publishedAt) : '未提供' }}
        </dd>
        <dt class="tech-key">accessed_at</dt>
        <dd class="tech-value">
          {{ source.accessedAt ? formatDateTime(source.accessedAt) : '未提供' }}
        </dd>
      </dl>
      <div class="separator" style="margin: 18px 0" />
      <div class="card-title">来源片段</div>
      <p
        style="
          margin: 10px 0 0;
          color: var(--text-secondary);
          font-size: 11px;
          line-height: 1.75;
        "
      >
        {{ source.content ?? source.contentPreview }}
      </p>
      <template v-if="Object.keys(source.metadata).length">
        <div class="separator" style="margin: 18px 0" />
        <dl class="tech-grid">
          <template v-for="(value, key) in source.metadata" :key="key">
            <dt class="tech-key">{{ key }}</dt>
            <dd class="tech-value">{{ value }}</dd>
          </template>
        </dl>
      </template>
      <AppButton style="margin-top: 18px" @click="copyContent">
        <Copy :size="14" aria-hidden="true" />
        复制正文
      </AppButton>
      <a
        v-if="source.sourceType === 'web' && source.url"
        class="button"
        style="margin: 18px 0 0 8px"
        :href="source.url"
        target="_blank"
        rel="noopener noreferrer"
      >
        <ExternalLink :size="14" aria-hidden="true" />
        打开安全链接
      </a>
    </template>
  </AppSheet>
</template>
