<script setup lang="ts">
import { File, UploadCloud, X } from 'lucide-vue-next'
import { computed, ref, watch } from 'vue'

import AppButton from '@/components/ui/AppButton.vue'
import AppDialog from '@/components/ui/AppDialog.vue'
import { formatFileSize } from '@/utils/format'

const props = defineProps<{
  open: boolean
  busy: boolean
}>()

const emit = defineEmits<{
  'update:open': [open: boolean]
  confirm: [files: File[]]
}>()

const input = ref<HTMLInputElement | null>(null)
const selected = ref<File[]>([])
const dragging = ref(false)
const error = ref('')
const allowed = new Set(['PDF', 'TXT', 'CSV', 'JSON'])

const canSubmit = computed(() => selected.value.length > 0 && error.value.length === 0)

watch(
  () => props.open,
  (open) => {
    if (open) {
      selected.value = []
      error.value = ''
      dragging.value = false
    }
  },
)

function addFiles(files: File[]): void {
  error.value = ''
  const accepted: File[] = []
  for (const file of files) {
    const extension = file.name.split('.').pop()?.toUpperCase() ?? ''
    if (!allowed.has(extension)) {
      error.value = '仅支持 PDF、TXT、CSV 和 JSON。'
      continue
    }
    accepted.push(file)
  }
  selected.value = [...selected.value, ...accepted].filter(
    (file, index, all) =>
      all.findIndex(
        (candidate) => candidate.name === file.name && candidate.size === file.size,
      ) === index,
  )
}

function onInput(event: Event): void {
  const target = event.target
  if (target instanceof HTMLInputElement && target.files) {
    addFiles(Array.from(target.files))
  }
}

function onDrop(event: DragEvent): void {
  dragging.value = false
  if (event.dataTransfer?.files) {
    addFiles(Array.from(event.dataTransfer.files))
  }
}

function removeFile(index: number): void {
  selected.value = selected.value.filter((_, itemIndex) => itemIndex !== index)
}
</script>

<template>
  <AppDialog
    :open="open"
    title="上传文件"
    description="文件将上传到当前数据源，并以 PENDING 状态等待处理。"
    @update:open="emit('update:open', $event)"
  >
    <input
      ref="input"
      class="sr-only"
      type="file"
      multiple
      accept=".pdf,.txt,.csv,.json"
      @change="onInput"
    />
    <button
      type="button"
      class="dropzone"
      :class="{ 'is-dragging': dragging }"
      @click="input?.click()"
      @dragenter.prevent="dragging = true"
      @dragover.prevent
      @dragleave.prevent="dragging = false"
      @drop.prevent="onDrop"
    >
      <span class="state-icon">
        <UploadCloud :size="20" aria-hidden="true" />
      </span>
      <strong style="margin-top: 12px; font-size: 11px">
        拖拽文件到此处，或点击选择
      </strong>
      <span class="state-copy">支持 PDF、TXT、CSV、JSON</span>
    </button>

    <div v-if="selected.length" class="compact-list card">
      <div v-for="(file, index) in selected" :key="file.name" class="compact-row">
        <div style="display: flex; min-width: 0; align-items: center; gap: 9px">
          <span class="file-glyph">
            <File :size="14" aria-hidden="true" />
          </span>
          <div class="truncate">
            <div class="compact-title">{{ file.name }}</div>
            <div class="compact-meta">{{ formatFileSize(file.size) }}</div>
          </div>
        </div>
        <AppButton
          size="icon"
          variant="ghost"
          aria-label="移除文件"
          @click="removeFile(index)"
        >
          <X :size="14" aria-hidden="true" />
        </AppButton>
      </div>
    </div>
    <p v-if="error" class="form-error" role="alert">{{ error }}</p>

    <template #footer>
      <AppButton @click="emit('update:open', false)">取消</AppButton>
      <AppButton
        variant="primary"
        :disabled="!canSubmit"
        :loading="busy"
        @click="emit('confirm', selected)"
      >
        加入处理队列
      </AppButton>
    </template>
  </AppDialog>
</template>
