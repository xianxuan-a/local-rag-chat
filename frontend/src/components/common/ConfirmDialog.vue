<script setup lang="ts">
import {
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogOverlay,
  AlertDialogPortal,
  AlertDialogRoot,
  AlertDialogTitle,
} from 'reka-ui'

defineProps<{
  open: boolean
  title: string
  description: string
  confirmLabel?: string
  busy?: boolean
}>()

const emit = defineEmits<{
  'update:open': [open: boolean]
  confirm: []
}>()
</script>

<template>
  <AlertDialogRoot :open="open" @update:open="emit('update:open', $event)">
    <AlertDialogPortal>
      <AlertDialogOverlay class="dialog-overlay" />
      <AlertDialogContent class="dialog-content">
        <div class="dialog-header">
          <AlertDialogTitle class="dialog-title">
            {{ title }}
          </AlertDialogTitle>
          <AlertDialogDescription class="dialog-description">
            {{ description }}
          </AlertDialogDescription>
        </div>
        <div class="dialog-footer" style="padding-top: 18px">
          <AlertDialogCancel class="button">取消</AlertDialogCancel>
          <button
            type="button"
            class="button button-danger"
            :disabled="busy"
            @click="emit('confirm')"
          >
            {{ busy ? '处理中…' : (confirmLabel ?? '确认删除') }}
          </button>
        </div>
      </AlertDialogContent>
    </AlertDialogPortal>
  </AlertDialogRoot>
</template>
