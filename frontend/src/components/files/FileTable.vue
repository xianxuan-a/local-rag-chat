<script setup lang="ts">
import { Eye, MoreHorizontal, Play, RotateCcw, Trash2 } from 'lucide-vue-next'

import FileStatusBadge from '@/components/files/FileStatusBadge.vue'
import AppButton from '@/components/ui/AppButton.vue'
import AppTooltip from '@/components/ui/AppTooltip.vue'
import type { FileRecord } from '@/types'
import { formatDateTime, formatFileSize, formatNumber } from '@/utils/format'

defineProps<{
  files: FileRecord[]
}>()

const emit = defineEmits<{
  view: [file: FileRecord]
  process: [file: FileRecord]
  remove: [file: FileRecord]
}>()
</script>

<template>
  <div class="table-scroll">
    <table class="data-table">
      <thead>
        <tr>
          <th>文件名</th>
          <th>大小</th>
          <th>类型</th>
          <th>状态</th>
          <th>分块数</th>
          <th>向量状态</th>
          <th>上传时间</th>
          <th style="text-align: right">操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="file in files" :key="file.id">
          <td>
            <div class="file-name-cell">
              <span class="file-glyph">
                <MoreHorizontal :size="14" aria-hidden="true" />
              </span>
              <div class="truncate">
                <div class="table-primary">{{ file.fileName }}</div>
                <div class="compact-meta mono">{{ file.id }}</div>
              </div>
            </div>
          </td>
          <td>{{ formatFileSize(file.fileSize) }}</td>
          <td>{{ file.fileType }}</td>
          <td>
            <div v-if="file.status === 'PROCESSING'" class="processing-cell">
              <div class="progress" :aria-label="`处理进度 ${file.progress}%`">
                <div class="progress-bar" :style="{ width: `${file.progress}%` }" />
              </div>
              <span>{{ file.progress }}%</span>
            </div>
            <FileStatusBadge v-else :status="file.status" />
          </td>
          <td>{{ file.chunkCount ? formatNumber(file.chunkCount) : '—' }}</td>
          <td class="mono">
            {{
              file.status === 'PROCESSING'
                ? 'building'
                : file.hasActiveVectors
                  ? 'active'
                  : file.status.toLowerCase()
            }}
          </td>
          <td>{{ formatDateTime(file.createdAt) }}</td>
          <td>
            <div class="table-actions">
              <AppTooltip text="查看文件详情">
                <AppButton
                  size="icon"
                  variant="ghost"
                  aria-label="查看文件详情"
                  @click="emit('view', file)"
                >
                  <Eye :size="13" aria-hidden="true" />
                </AppButton>
              </AppTooltip>
              <AppTooltip :text="file.status === 'FAILED' ? '重试处理' : '处理文件'">
                <AppButton
                  size="icon"
                  variant="ghost"
                  :disabled="file.status === 'PROCESSING' || file.status === 'SUCCESS'"
                  :aria-label="file.status === 'FAILED' ? '重试处理文件' : '处理文件'"
                  @click="emit('process', file)"
                >
                  <RotateCcw
                    v-if="file.status === 'FAILED'"
                    :size="13"
                    aria-hidden="true"
                  />
                  <Play v-else :size="13" aria-hidden="true" />
                </AppButton>
              </AppTooltip>
              <AppTooltip text="删除文件">
                <AppButton
                  size="icon"
                  variant="ghost"
                  :disabled="file.status === 'PROCESSING'"
                  aria-label="删除文件"
                  @click="emit('remove', file)"
                >
                  <Trash2 :size="13" aria-hidden="true" />
                </AppButton>
              </AppTooltip>
            </div>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
