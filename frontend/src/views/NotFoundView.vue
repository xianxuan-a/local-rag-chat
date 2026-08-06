<script setup lang="ts">
import { ArrowLeft, Compass } from 'lucide-vue-next'
import { RouterLink } from 'vue-router'

import AppButton from '@/components/ui/AppButton.vue'
</script>

<template>
  <main class="not-found">
    <section class="card not-found-card">
      <span class="state-icon" style="margin: 0 auto">
        <Compass :size="20" aria-hidden="true" />
      </span>
      <div class="not-found-code">404</div>
      <h1 class="state-title">页面不存在</h1>
      <p class="state-copy">
        你访问的路径可能已移动或从未创建。返回系统总览继续使用 Nexus RAG。
      </p>
      <div class="state-actions" style="justify-content: center">
        <RouterLink to="/dashboard">
          <AppButton variant="primary">
            <ArrowLeft :size="14" aria-hidden="true" />
            返回系统总览
          </AppButton>
        </RouterLink>
      </div>
    </section>
  </main>
</template>
