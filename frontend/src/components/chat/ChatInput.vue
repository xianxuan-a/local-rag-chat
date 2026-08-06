<script setup lang="ts">
import { Send, Square } from 'lucide-vue-next'

import AppButton from '@/components/ui/AppButton.vue'
import type { RetrievalMode } from '@/types'

const props = defineProps<{
  modelValue: string
  generating: boolean
  stopping: boolean
  stopDisabled: boolean
  disabled: boolean
  disabledReason?: string
  knowledgeBaseName: string
  mode: RetrievalMode
  modeNotice?: string
}>()

const emit = defineEmits<{
  'update:modelValue': [value: string]
  'update:mode': [value: RetrievalMode]
  send: []
  stop: []
}>()

function onInput(event: Event): void {
  const target = event.target
  if (target instanceof HTMLTextAreaElement) {
    emit('update:modelValue', target.value)
  }
}

function onKeydown(event: KeyboardEvent): void {
  if (event.key !== 'Enter' || event.shiftKey) return
  event.preventDefault()
  if (!props.generating && !props.disabled && props.modelValue.trim()) emit('send')
}
</script>

<template>
  <div class="chat-composer-wrap">
    <div class="chat-composer">
      <label>
        <span class="sr-only">输入问题</span>
        <textarea
          :value="modelValue"
          :placeholder="
            disabledReason || `继续提问 ${knowledgeBaseName || '当前知识库'}…`
          "
          :disabled="generating"
          @input="onInput"
          @keydown="onKeydown"
        />
      </label>
      <div class="composer-foot">
        <span>
          {{ disabledReason || modeNotice || 'Enter 发送 · Shift + Enter 换行' }}
        </span>
        <div style="display: flex; align-items: center; gap: 8px">
          <label>
            <span class="sr-only">检索模式</span>
            <select
              class="native-select"
              :value="mode"
              :disabled="generating"
              aria-label="检索模式"
              @change="
                $emit(
                  'update:mode',
                  ($event.target as HTMLSelectElement).value as RetrievalMode,
                )
              "
            >
              <option value="knowledge_only">仅知识库</option>
              <option value="knowledge_first">知识库优先</option>
              <option value="hybrid">混合检索</option>
            </select>
          </label>
          <span class="badge badge-light">{{ knowledgeBaseName }}</span>
          <AppButton
            v-if="generating"
            size="icon"
            :disabled="stopping || stopDisabled"
            :loading="stopping"
            aria-label="停止生成"
            @click="emit('stop')"
          >
            <Square :size="13" aria-hidden="true" />
          </AppButton>
          <AppButton
            v-else
            size="icon"
            variant="primary"
            :disabled="disabled || !modelValue.trim()"
            aria-label="发送问题"
            @click="emit('send')"
          >
            <Send :size="14" aria-hidden="true" />
          </AppButton>
        </div>
      </div>
    </div>
  </div>
</template>
