<script setup lang="ts">
import { X } from 'lucide-vue-next'
import {
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogOverlay,
  DialogPortal,
  DialogRoot,
  DialogTitle,
} from 'reka-ui'

import AppButton from '@/components/ui/AppButton.vue'

defineProps<{
  open: boolean
  title: string
  description: string
}>()

const emit = defineEmits<{
  'update:open': [open: boolean]
}>()
</script>

<template>
  <DialogRoot :open="open" @update:open="emit('update:open', $event)">
    <DialogPortal>
      <DialogOverlay class="dialog-overlay" />
      <DialogContent class="dialog-content">
        <div class="dialog-header">
          <DialogTitle class="dialog-title">{{ title }}</DialogTitle>
          <DialogDescription class="dialog-description">
            {{ description }}
          </DialogDescription>
        </div>
        <DialogClose as-child>
          <AppButton
            class="dialog-close"
            size="icon"
            variant="ghost"
            aria-label="关闭对话框"
          >
            <X :size="16" aria-hidden="true" />
          </AppButton>
        </DialogClose>
        <div class="dialog-body">
          <slot />
        </div>
        <div v-if="$slots.footer" class="dialog-footer">
          <slot name="footer" />
        </div>
      </DialogContent>
    </DialogPortal>
  </DialogRoot>
</template>
