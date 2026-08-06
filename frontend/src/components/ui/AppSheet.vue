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

withDefaults(
  defineProps<{
    open: boolean
    title: string
    description: string
    wide?: boolean
  }>(),
  {
    wide: false,
  },
)

const emit = defineEmits<{
  'update:open': [open: boolean]
}>()
</script>

<template>
  <DialogRoot :open="open" @update:open="emit('update:open', $event)">
    <DialogPortal>
      <DialogOverlay class="sheet-overlay" />
      <DialogContent class="sheet-content" :class="{ 'sheet-wide': wide }">
        <div class="sheet-header">
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
            aria-label="关闭侧边面板"
          >
            <X :size="16" aria-hidden="true" />
          </AppButton>
        </DialogClose>
        <div class="sheet-body">
          <slot />
        </div>
      </DialogContent>
    </DialogPortal>
  </DialogRoot>
</template>
