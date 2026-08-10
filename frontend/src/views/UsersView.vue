<script setup lang="ts">
import { RefreshCw, ShieldCheck, UserCog } from 'lucide-vue-next'
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { toast } from 'vue-sonner'

import { apiClient } from '@/api/client'
import ErrorState from '@/components/common/ErrorState.vue'
import LoadingState from '@/components/common/LoadingState.vue'
import PageHeader from '@/components/common/PageHeader.vue'
import AppButton from '@/components/ui/AppButton.vue'
import { useAuthStore } from '@/stores/auth'
import type {
  AdminUserPage,
  AuthenticatedUser,
  UserAdminAuditEventPage,
  UserRole,
} from '@/types'
import { isAbortError } from '@/utils/abort'
import { getErrorMessage } from '@/utils/error'
import { formatDateTime } from '@/utils/format'

const PAGE_SIZE = 50
const authStore = useAuthStore()
const users = ref<AdminUserPage | null>(null)
const auditEvents = ref<UserAdminAuditEventPage | null>(null)
const loading = ref(true)
const error = ref<unknown>(null)
const savingId = ref<string | null>(null)
const query = ref('')
const roleFilter = ref<'' | UserRole>('')
const activeFilter = ref<'' | 'true' | 'false'>('')
const offset = ref(0)
const draftRoles = reactive<Record<string, UserRole>>({})
const reasons = reactive<Record<string, string>>({})
let controller = new AbortController()

const hasPrevious = computed(() => offset.value > 0)
const hasNext = computed(
  () =>
    users.value !== null && offset.value + users.value.items.length < users.value.total,
)

function activeFilterValue(): boolean | undefined {
  if (activeFilter.value === '') return undefined
  return activeFilter.value === 'true'
}

async function load(): Promise<void> {
  controller.abort()
  controller = new AbortController()
  loading.value = true
  error.value = null
  try {
    const [userPage, auditPage] = await Promise.all([
      apiClient.listUsers({
        query: query.value,
        ...(roleFilter.value ? { role: roleFilter.value } : {}),
        ...(activeFilterValue() === undefined
          ? {}
          : { isActive: activeFilterValue()! }),
        limit: PAGE_SIZE,
        offset: offset.value,
        signal: controller.signal,
      }),
      apiClient.listUserAuditEvents({
        limit: 20,
        offset: 0,
        signal: controller.signal,
      }),
    ])
    users.value = userPage
    auditEvents.value = auditPage
    for (const user of userPage.items) draftRoles[user.id] = user.role
  } catch (caught) {
    if (!isAbortError(caught)) error.value = caught
  } finally {
    loading.value = false
  }
}

function applyFilters(): void {
  offset.value = 0
  void load()
}

async function updateUser(
  user: AuthenticatedUser,
  change: { role?: UserRole; isActive?: boolean },
): Promise<void> {
  savingId.value = user.id
  try {
    await apiClient.updateUser(user.id, {
      ...change,
      reason: reasons[user.id]?.trim() || null,
    })
    reasons[user.id] = ''
    toast.success('用户权限状态已更新')
    await load()
  } catch (caught) {
    toast.error(getErrorMessage(caught))
  } finally {
    savingId.value = null
  }
}

function saveRole(user: AuthenticatedUser): void {
  const role = draftRoles[user.id]
  if (!role || role === user.role) return
  void updateUser(user, { role })
}

function toggleActive(user: AuthenticatedUser): void {
  const next = !user.isActive
  if (!next && !window.confirm(`确认停用用户 ${user.username}？`)) return
  void updateUser(user, { isActive: next })
}

function previousPage(): void {
  offset.value = Math.max(0, offset.value - PAGE_SIZE)
  void load()
}

function nextPage(): void {
  offset.value += PAGE_SIZE
  void load()
}

onMounted(() => void load())
onBeforeUnmount(() => controller.abort())
</script>

<template>
  <section class="page-stack">
    <PageHeader
      title="用户管理"
      description="管理账户角色、启停状态并查看不可变更的管理员审计记录"
    >
      <template #actions>
        <AppButton :disabled="loading" @click="load">
          <RefreshCw :size="14" aria-hidden="true" />
          刷新
        </AppButton>
      </template>
    </PageHeader>

    <div class="card user-filters">
      <label>
        <span>搜索</span>
        <input v-model="query" placeholder="用户名或邮箱" @keyup.enter="applyFilters" />
      </label>
      <label>
        <span>角色</span>
        <select v-model="roleFilter">
          <option value="">全部角色</option>
          <option value="ADMIN">ADMIN</option>
          <option value="USER">USER</option>
        </select>
      </label>
      <label>
        <span>状态</span>
        <select v-model="activeFilter">
          <option value="">全部状态</option>
          <option value="true">已启用</option>
          <option value="false">已停用</option>
        </select>
      </label>
      <AppButton variant="primary" @click="applyFilters">应用筛选</AppButton>
    </div>

    <LoadingState v-if="loading && users === null" label="正在读取用户…" />
    <ErrorState
      v-else-if="error"
      title="用户列表加载失败"
      :message="getErrorMessage(error)"
      @retry="load"
    />
    <div v-else-if="users" class="card table-card">
      <div class="user-summary">
        <span>
          <UserCog :size="15" aria-hidden="true" />
          共 {{ users.total }} 个账户
        </span>
        <span>
          第 {{ users.offset + 1 }}–{{ users.offset + users.items.length }} 条
        </span>
      </div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>用户</th>
              <th>角色</th>
              <th>状态</th>
              <th>变更原因</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="user in users.items" :key="user.id">
              <td>
                <strong>{{ user.username }}</strong>
                <small>{{ user.email ?? '未设置邮箱' }}</small>
              </td>
              <td>
                <select
                  v-model="draftRoles[user.id]"
                  :disabled="user.id === authStore.user?.id || savingId === user.id"
                  :aria-label="`修改 ${user.username} 的角色`"
                >
                  <option value="ADMIN">ADMIN</option>
                  <option value="USER">USER</option>
                </select>
              </td>
              <td>
                <span
                  class="badge"
                  :class="user.isActive ? 'badge-success' : 'badge-light'"
                >
                  {{ user.isActive ? '已启用' : '已停用' }}
                </span>
              </td>
              <td>
                <input
                  v-model="reasons[user.id]"
                  maxlength="500"
                  placeholder="可选审计说明"
                  :aria-label="`${user.username} 的变更原因`"
                />
              </td>
              <td>
                <div class="table-actions">
                  <AppButton
                    size="sm"
                    :disabled="
                      user.id === authStore.user?.id ||
                      draftRoles[user.id] === user.role ||
                      savingId === user.id
                    "
                    @click="saveRole(user)"
                  >
                    保存角色
                  </AppButton>
                  <AppButton
                    size="sm"
                    :disabled="user.id === authStore.user?.id || savingId === user.id"
                    @click="toggleActive(user)"
                  >
                    {{ user.isActive ? '停用' : '启用' }}
                  </AppButton>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div class="pagination-actions">
        <AppButton :disabled="!hasPrevious" @click="previousPage">上一页</AppButton>
        <AppButton :disabled="!hasNext" @click="nextPage">下一页</AppButton>
      </div>
    </div>

    <div class="card audit-card">
      <div class="section-title">
        <ShieldCheck :size="16" aria-hidden="true" />
        <h2>最近管理员审计</h2>
      </div>
      <p v-if="!auditEvents?.items.length" class="muted">暂无角色或状态变更。</p>
      <ol v-else class="audit-list">
        <li v-for="event in auditEvents.items" :key="event.id">
          <div>
            <strong>{{ event.targetUserId }}</strong>
            <span>
              {{ event.beforeState.role }} /
              {{ event.beforeState.isActive ? '启用' : '停用' }}
              →
              {{ event.afterState.role }} /
              {{ event.afterState.isActive ? '启用' : '停用' }}
            </span>
          </div>
          <small>
            {{ event.reason ?? '未填写原因' }} · {{ formatDateTime(event.createdAt) }}
          </small>
        </li>
      </ol>
    </div>
  </section>
</template>

<style scoped>
.user-filters {
  display: grid;
  grid-template-columns: minmax(220px, 1fr) 150px 150px auto;
  gap: 12px;
  align-items: end;
  padding: 16px;
}

.user-filters label,
.table-card td:first-child {
  display: grid;
  gap: 6px;
}

.user-filters label span,
.table-card small,
.muted,
.audit-list small {
  color: var(--text-secondary);
}

.user-summary,
.pagination-actions,
.section-title,
.audit-list li > div {
  display: flex;
  align-items: center;
}

.user-summary {
  justify-content: space-between;
  padding: 14px 16px;
  border-bottom: 1px solid var(--border);
  color: var(--text-secondary);
}

.user-summary span,
.section-title {
  gap: 8px;
}

.table-card input,
.table-card select {
  min-width: 150px;
}

.pagination-actions {
  justify-content: flex-end;
  gap: 8px;
  padding: 14px 16px;
  border-top: 1px solid var(--border);
}

.audit-card {
  padding: 18px;
}

.section-title h2 {
  margin: 0;
  font-size: 16px;
}

.audit-list {
  display: grid;
  gap: 0;
  margin: 16px 0 0;
  padding: 0;
  list-style: none;
}

.audit-list li {
  display: grid;
  gap: 6px;
  padding: 12px 0;
  border-top: 1px solid var(--border);
}

.audit-list li > div {
  justify-content: space-between;
  gap: 16px;
}

@media (max-width: 900px) {
  .user-filters {
    grid-template-columns: 1fr 1fr;
  }
}

@media (max-width: 640px) {
  .user-filters {
    grid-template-columns: 1fr;
  }
}
</style>
