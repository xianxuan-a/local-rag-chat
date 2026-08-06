<script setup lang="ts">
import { computed } from 'vue'

import { renderMarkdown } from '@/utils/markdown'

const props = defineProps<{
  content: string
}>()

const html = computed(() => renderMarkdown(props.content))
</script>

<template>
  <!-- HTML is produced by the dedicated Markdown parser and DOMPurify. -->
  <div class="markdown" v-html="html" />
</template>
