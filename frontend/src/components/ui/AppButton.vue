<script setup lang="ts">
import { LoaderCircle } from 'lucide-vue-next'

withDefaults(
  defineProps<{
    type?: 'button' | 'submit' | 'reset'
    variant?: 'default' | 'primary' | 'ghost' | 'danger'
    size?: 'sm' | 'default' | 'lg' | 'icon'
    disabled?: boolean
    loading?: boolean
    ariaLabel?: string | undefined
  }>(),
  {
    type: 'button',
    variant: 'default',
    size: 'default',
    disabled: false,
    loading: false,
    ariaLabel: undefined,
  },
)
</script>

<template>
  <button
    :type="type"
    class="button"
    :class="[`button-${variant}`, size !== 'default' ? `button-${size}` : '']"
    :disabled="disabled || loading"
    :aria-label="ariaLabel"
    :aria-busy="loading"
  >
    <LoaderCircle v-if="loading" :size="15" class="spin" aria-hidden="true" />
    <slot />
  </button>
</template>
