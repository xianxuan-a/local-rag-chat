<script setup lang="ts">
import { MessageSquareText, Trash2 } from 'lucide-vue-next'

import AppButton from '@/components/ui/AppButton.vue'
import type { ChatSession, KnowledgeBase } from '@/types'
import { formatDateTime } from '@/utils/format'

defineProps<{
  sessions: ChatSession[]
  knowledgeBases: KnowledgeBase[]
  currentId: string
  allowDelete?: boolean
}>()

const emit = defineEmits<{
  select: [id: string]
  remove: [session: ChatSession]
}>()

function knowledgeBaseName(knowledgeBases: KnowledgeBase[], id: string): string {
  return knowledgeBases.find((item) => item.id === id)?.name ?? '未知知识库'
}
</script>

<template>
  <div class="session-list">
    <div
      v-for="session in sessions"
      :key="session.id"
      class="session-item"
      :class="{ 'is-active': session.id === currentId }"
    >
      <button
        type="button"
        style="width: 100%; padding: 0; text-align: left; background: transparent"
        @click="emit('select', session.id)"
      >
        <div class="session-title">{{ session.title }}</div>
        <div class="session-meta">
          <span class="truncate">
            {{ knowledgeBaseName(knowledgeBases, session.knowledgeBaseId) }}
          </span>
          <span>{{ formatDateTime(session.updatedAt) }}</span>
        </div>
      </button>
      <AppButton
        v-if="allowDelete"
        class="session-delete"
        size="icon"
        variant="ghost"
        aria-label="删除会话"
        @click.stop="emit('remove', session)"
      >
        <Trash2 :size="12" aria-hidden="true" />
      </AppButton>
    </div>
    <div v-if="sessions.length === 0" class="state-view" style="min-height: 180px">
      <div class="state-icon">
        <MessageSquareText :size="18" aria-hidden="true" />
      </div>
      <div class="state-title">没有匹配会话</div>
      <div class="state-copy">调整搜索条件，或新建一个会话。</div>
    </div>
  </div>
</template>
