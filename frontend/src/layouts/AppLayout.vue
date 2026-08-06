<script setup lang="ts">
import { Menu, Sparkles } from 'lucide-vue-next'

import AppSidebar from '@/components/common/AppSidebar.vue'
import AppButton from '@/components/ui/AppButton.vue'
import AppSheet from '@/components/ui/AppSheet.vue'
import { useAppStore } from '@/stores/app'

const appStore = useAppStore()
</script>

<template>
  <div class="app-shell" :class="{ 'is-collapsed': appStore.sidebarCollapsed }">
    <AppSidebar />
    <main class="app-main">
      <div class="mobile-topbar">
        <div class="mobile-brand">
          <span class="brand-mark" style="width: 28px; height: 28px">
            <Sparkles :size="14" aria-hidden="true" />
          </span>
          Nexus RAG
        </div>
        <AppButton
          size="icon"
          variant="ghost"
          aria-label="打开主导航"
          @click="appStore.setMobileNavigation(true)"
        >
          <Menu :size="18" aria-hidden="true" />
        </AppButton>
      </div>
      <RouterView />
    </main>
  </div>

  <AppSheet
    :open="appStore.mobileNavigationOpen"
    title="Nexus RAG"
    description="选择工作区页面"
    @update:open="appStore.setMobileNavigation"
  >
    <div style="margin: -18px -20px -28px; height: calc(100vh - 77px)">
      <AppSidebar mobile @navigate="appStore.setMobileNavigation(false)" />
    </div>
  </AppSheet>
</template>
