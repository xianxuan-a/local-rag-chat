<script setup lang="ts">
import { onBeforeUnmount, onMounted } from 'vue'
import { Toaster } from 'vue-sonner'
import { useRouter } from 'vue-router'

import { onAuthenticationExpired } from '@/api/auth'
import { safeInternalRedirect } from '@/router'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const authStore = useAuthStore()
let stopAuthenticationListener: (() => void) | null = null

onMounted(() => {
  stopAuthenticationListener = onAuthenticationExpired(() => {
    authStore.clearSession()
    const currentRoute = router.currentRoute.value
    if (currentRoute.name === 'login') return
    void router.replace({
      path: '/login',
      query: { redirect: safeInternalRedirect(currentRoute.fullPath) },
    })
  })
})

onBeforeUnmount(() => {
  stopAuthenticationListener?.()
  stopAuthenticationListener = null
})
</script>

<template>
  <RouterView />
  <Toaster
    position="top-right"
    :duration="2800"
    :toast-options="{
      classes: {
        toast: 'nexus-toast',
        title: 'nexus-toast-title',
        description: 'nexus-toast-description',
        actionButton: 'nexus-toast-action',
        cancelButton: 'nexus-toast-cancel',
      },
    }"
  />
</template>
