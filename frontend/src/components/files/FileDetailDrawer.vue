<script setup lang="ts">
import { Copy, FileText } from 'lucide-vue-next'
import { ref, watch } from 'vue'
import { toast } from 'vue-sonner'

import FileStatusBadge from '@/components/files/FileStatusBadge.vue'
import FileTechnicalDetails from '@/components/files/FileTechnicalDetails.vue'
import AppButton from '@/components/ui/AppButton.vue'
import AppSheet from '@/components/ui/AppSheet.vue'
import AppSwitch from '@/components/ui/AppSwitch.vue'
import type { FileRecord } from '@/types'
import { formatDateTime, formatFileSize } from '@/utils/format'

const props = defineProps<{
  open: boolean
  file: FileRecord | null
}>()

const emit = defineEmits<{
  'update:open': [open: boolean]
}>()

const showTechnical = ref(false)

watch(
  () => props.file?.id,
  () => {
    showTechnical.value = false
  },
)

async function copyIdentifier(): Promise<void> {
  if (props.file === null) return
  await navigator.clipboard.writeText(props.file.id)
  toast.success('file_id 已复制')
}
</script>

<template>
  <AppSheet
    :open="open"
    title="文件详情"
    description="查看文件处理状态、索引信息与错误详情"
    wide
    @update:open="emit('update:open', $event)"
  >
    <template v-if="file">
      <div style="display: flex; align-items: flex-start; gap: 12px">
        <span class="file-glyph">
          <FileText :size="16" aria-hidden="true" />
        </span>
        <div style="min-width: 0; flex: 1">
          <h2 style="margin: 0; font-size: 14px">{{ file.fileName }}</h2>
          <div class="compact-meta">
            {{ formatFileSize(file.fileSize) }} · {{ file.fileType }} ·
            {{ formatDateTime(file.createdAt) }}
          </div>
        </div>
        <FileStatusBadge :status="file.status" />
      </div>

      <div class="separator" style="margin: 18px 0" />

      <div class="system-info-grid" style="grid-template-columns: repeat(3, 1fr)">
        <div class="info-tile">
          <div class="info-label">分块数量</div>
          <div class="info-value">{{ file.chunkCount }} chunks</div>
        </div>
        <div class="info-tile">
          <div class="info-label">向量状态</div>
          <div class="info-value">
            {{ file.hasActiveVectors ? 'active' : 'inactive' }}
          </div>
        </div>
        <div class="info-tile">
          <div class="info-label">处理进度</div>
          <div class="info-value">{{ file.progress }}%</div>
        </div>
      </div>

      <div v-if="file.errorMessage" class="error-banner">
        <div>
          <div class="table-primary">处理异常</div>
          <div class="compact-meta mono">{{ file.errorMessage }}</div>
        </div>
      </div>

      <div class="separator" style="margin: 18px 0" />
      <div class="switch-row">
        <div>
          <div class="card-title">显示技术详情</div>
          <div class="card-description">展开索引、向量和错误字段</div>
        </div>
        <AppSwitch v-model="showTechnical" label="显示文件技术详情" />
      </div>

      <div v-if="showTechnical" style="margin-top: 18px">
        <FileTechnicalDetails :file="file" />
        <AppButton style="margin-top: 16px" @click="copyIdentifier">
          <Copy :size="14" aria-hidden="true" />
          复制 file_id
        </AppButton>
      </div>
    </template>
  </AppSheet>
</template>
