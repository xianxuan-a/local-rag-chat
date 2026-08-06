<script setup lang="ts">
import { ThumbsDown, ThumbsUp } from 'lucide-vue-next'

import AppButton from '@/components/ui/AppButton.vue'
import AppTooltip from '@/components/ui/AppTooltip.vue'
import type { AnswerFeedback } from '@/types'

defineProps<{
  feedback: AnswerFeedback
  disabled?: boolean
}>()

const emit = defineEmits<{
  change: [feedback: AnswerFeedback]
}>()
</script>

<template>
  <div style="display: flex; gap: 2px">
    <AppTooltip text="回答有帮助">
      <AppButton
        size="icon"
        :variant="feedback === 'like' ? 'default' : 'ghost'"
        :disabled="disabled"
        aria-label="点赞回答"
        @click="emit('change', feedback === 'like' ? null : 'like')"
      >
        <ThumbsUp :size="12" aria-hidden="true" />
      </AppButton>
    </AppTooltip>
    <AppTooltip text="回答需要改进">
      <AppButton
        size="icon"
        :variant="feedback === 'dislike' ? 'default' : 'ghost'"
        :disabled="disabled"
        aria-label="点踩回答"
        @click="emit('change', feedback === 'dislike' ? null : 'dislike')"
      >
        <ThumbsDown :size="12" aria-hidden="true" />
      </AppButton>
    </AppTooltip>
  </div>
</template>
