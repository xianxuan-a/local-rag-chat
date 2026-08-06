<script setup lang="ts">
import {
  ChevronsLeft,
  ChevronsRight,
  Database,
  Files,
  FlaskConical,
  History,
  Layers3,
  LayoutDashboard,
  LogOut,
  MessageSquareText,
  Search,
  Settings,
  Sparkles,
  UserRound,
} from 'lucide-vue-next'
import { computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'

import { apiConfig } from '@/api/client'
import AppButton from '@/components/ui/AppButton.vue'
import AppTooltip from '@/components/ui/AppTooltip.vue'
import { useAppStore } from '@/stores/app'
import { useAuthStore } from '@/stores/auth'
import { useKnowledgeBaseStore } from '@/stores/knowledgeBase'

const props = withDefaults(
  defineProps<{
    mobile?: boolean
  }>(),
  {
    mobile: false,
  },
)

const emit = defineEmits<{
  navigate: []
}>()

const appStore = useAppStore()
const authStore = useAuthStore()
const knowledgeBaseStore = useKnowledgeBaseStore()
const router = useRouter()

const navigation = [
  { to: '/dashboard', label: '系统总览', icon: LayoutDashboard },
  { to: '/chat', label: '智能问答', icon: MessageSquareText },
  { to: '/knowledge-bases', label: '知识库', icon: Database },
  { to: '/files', label: '文件管理', icon: Files },
  { to: '/sessions', label: '会话历史', icon: History },
  { to: '/retrieval', label: '检索测试', icon: Search },
  { to: '/indexes', label: '索引管理', icon: Layers3 },
  { to: '/evaluation', label: 'RAG 评测', icon: FlaskConical },
  { to: '/settings', label: '系统设置', icon: Settings },
]

const collapsed = computed(() => !props.mobile && appStore.sidebarCollapsed)
const accountName = computed(() => authStore.user?.username ?? '认证会话')
const accountRole = computed(() => authStore.user?.role ?? 'SIGNED IN')

function onKnowledgeBaseChange(event: Event): void {
  const target = event.target
  if (target instanceof HTMLSelectElement) {
    knowledgeBaseStore.setCurrent(target.value)
  }
}

function logout(): void {
  authStore.clearSession()
  emit('navigate')
  void router.replace('/login')
}

onMounted(() => {
  void knowledgeBaseStore.load().catch(() => undefined)
})
</script>

<template>
  <aside class="app-sidebar" :aria-label="props.mobile ? '移动端主导航' : '主导航'">
    <div class="brand">
      <span class="brand-mark">
        <Sparkles :size="15" aria-hidden="true" />
      </span>
      <div class="brand-copy">
        <div class="brand-title">Nexus RAG</div>
        <div class="brand-subtitle">Knowledge OS</div>
      </div>
    </div>

    <div class="sidebar-kb">
      <AppTooltip
        v-if="collapsed"
        :text="knowledgeBaseStore.current?.name ?? '选择知识库'"
      >
        <button
          class="select-trigger"
          type="button"
          aria-label="当前知识库"
          @click="appStore.toggleSidebar"
        >
          <Database :size="15" aria-hidden="true" />
        </button>
      </AppTooltip>
      <label v-else>
        <span class="sr-only">当前知识库</span>
        <select
          class="native-select"
          :value="knowledgeBaseStore.currentId"
          @change="onKnowledgeBaseChange"
        >
          <option
            v-for="item in knowledgeBaseStore.items"
            :key="item.id"
            :value="item.id"
          >
            {{ item.name }}
          </option>
        </select>
      </label>
    </div>

    <div class="nav-label">工作区</div>
    <nav class="sidebar-nav">
      <AppTooltip v-for="item in navigation" :key="item.to" :text="item.label">
        <RouterLink class="nav-item" :to="item.to" @click="emit('navigate')">
          <component :is="item.icon" :size="16" aria-hidden="true" />
          <span class="nav-item-copy">{{ item.label }}</span>
        </RouterLink>
      </AppTooltip>
    </nav>

    <div class="sidebar-footer">
      <template v-if="apiConfig.mode === 'real'">
        <div v-if="!collapsed" class="sidebar-account">
          <span class="sidebar-account-icon" aria-hidden="true">
            <UserRound :size="14" />
          </span>
          <span class="sidebar-account-copy">
            <strong>{{ accountName }}</strong>
            <small>{{ accountRole }}</small>
          </span>
        </div>
        <AppTooltip :text="collapsed ? '退出登录' : ''">
          <AppButton
            class="sidebar-logout"
            variant="ghost"
            aria-label="退出登录"
            @click="logout"
          >
            <LogOut :size="15" aria-hidden="true" />
            <span v-if="!collapsed" class="button-copy">退出登录</span>
          </AppButton>
        </AppTooltip>
      </template>
      <AppTooltip v-if="!props.mobile" :text="collapsed ? '展开侧边栏' : '折叠侧边栏'">
        <AppButton
          class="sidebar-collapse"
          variant="ghost"
          :aria-label="collapsed ? '展开侧边栏' : '折叠侧边栏'"
          @click="appStore.toggleSidebar"
        >
          <ChevronsRight v-if="collapsed" :size="15" aria-hidden="true" />
          <ChevronsLeft v-else :size="15" aria-hidden="true" />
          <span class="button-copy">{{ collapsed ? '展开' : '折叠侧边栏' }}</span>
        </AppButton>
      </AppTooltip>
    </div>
  </aside>
</template>
