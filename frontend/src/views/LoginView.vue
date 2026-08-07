<script setup lang="ts">
import { gsap } from 'gsap'
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import KnowledgeStarMap from '@/components/auth/KnowledgeStarMap.vue'
import { apiConfig } from '@/api/client'
import { loginModePresentation } from '@/api/loginMode'
import { safeInternalRedirect } from '@/router'
import { useAuthStore } from '@/stores/auth'
import { AppError } from '@/types'
import { getErrorMessage } from '@/utils/error'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()

type KnowledgeGroup = 'core' | 'identity' | 'security'

interface KnowledgeStarMapHandle {
  setFocus: (group: KnowledgeGroup, active: boolean) => void
  capture: () => void
  restore: () => void
}

const pageRef = ref<HTMLElement | null>(null)
const cardRef = ref<HTMLElement | null>(null)
const passwordInputRef = ref<HTMLInputElement | null>(null)
const statusRef = ref<HTMLParagraphElement | null>(null)
const starMapRef = ref<KnowledgeStarMapHandle | null>(null)

const identity = ref('')
const password = ref('')
const showPassword = ref(false)
const identityError = ref('')
const passwordError = ref('')
const formMessage = ref('')
const formMessageKind = ref<'error' | 'info'>('error')

const isSubmitting = computed(() => authStore.status === 'submitting')
const passwordType = computed(() => (showPassword.value ? 'text' : 'password'))
const passwordToggleLabel = computed(() =>
  showPassword.value ? '隐藏密码' : '显示密码',
)

let introMedia: ReturnType<typeof gsap.matchMedia> | null = null

function passwordByteLength(value: string): number {
  return new TextEncoder().encode(value).length
}

function validateForm(): boolean {
  identityError.value = ''
  passwordError.value = ''

  const normalizedIdentity = identity.value.trim()
  if (!normalizedIdentity) {
    identityError.value = '请输入用户名或邮箱。'
  } else if (normalizedIdentity.length > 320) {
    identityError.value = '用户名或邮箱不能超过 320 个字符。'
  }

  const bytes = passwordByteLength(password.value)
  if (!password.value) {
    passwordError.value = '请输入密码。'
  } else if (bytes < 12) {
    passwordError.value = '密码至少需要 12 个 UTF-8 字节。'
  } else if (bytes > 72) {
    passwordError.value = '密码不能超过 72 个 UTF-8 字节。'
  }

  return !identityError.value && !passwordError.value
}

function clearIdentityError(): void {
  identityError.value = ''
  if (formMessageKind.value === 'error') formMessage.value = ''
}

function clearPasswordError(): void {
  passwordError.value = ''
  if (formMessageKind.value === 'error') formMessage.value = ''
}

function setKnowledgeFocus(group: KnowledgeGroup, active: boolean): void {
  starMapRef.value?.setFocus(group, active)
}

function togglePassword(): void {
  showPassword.value = !showPassword.value
  void nextTick(() => passwordInputRef.value?.focus({ preventScroll: true }))
}

function loginErrorMessage(error: unknown): string {
  if (error instanceof AppError) {
    if (error.status === 401) return '用户名、邮箱或密码不正确。'
    if (error.status === 403) return '当前账户无法登录，请联系系统管理员。'
    if (error.status === 422) return '账号或密码格式不符合认证服务要求。'
    if (error.status === 429) return '尝试次数过多，请稍后再试。'
    if (error.status !== null && error.status >= 500) {
      return '认证服务暂时不可用，请稍后再试。'
    }
  }
  return getErrorMessage(error)
}

async function animateMessage(): Promise<void> {
  await nextTick()
  if (
    !statusRef.value ||
    window.matchMedia('(prefers-reduced-motion: reduce)').matches
  ) {
    return
  }
  gsap.fromTo(
    statusRef.value,
    { y: 6, autoAlpha: 0 },
    { y: 0, autoAlpha: 1, duration: 0.35, ease: 'power2.out' },
  )
}

async function handleSubmit(): Promise<void> {
  if (isSubmitting.value) return
  formMessage.value = ''
  if (!validateForm()) return

  if (loginModePresentation.submitMessage !== null) {
    formMessageKind.value = 'info'
    formMessage.value = loginModePresentation.submitMessage
    await animateMessage()
    return
  }

  starMapRef.value?.capture()
  if (cardRef.value) {
    gsap.to(cardRef.value, {
      scale: 0.992,
      duration: 0.28,
      ease: 'power3.inOut',
      overwrite: 'auto',
    })
  }

  try {
    await authStore.login(identity.value, password.value)
    const destination = safeInternalRedirect(route.query.redirect)
    await router.replace(destination)
  } catch (error) {
    formMessageKind.value = 'error'
    formMessage.value = loginErrorMessage(error)
    starMapRef.value?.restore()
    if (cardRef.value) {
      gsap.to(cardRef.value, {
        scale: 1,
        duration: 0.34,
        ease: 'power3.out',
        overwrite: 'auto',
      })
    }
    await animateMessage()
  }
}

onMounted(() => {
  const page = pageRef.value
  const card = cardRef.value
  if (!page || !card) return

  introMedia = gsap.matchMedia()
  introMedia.add(
    {
      reduceMotion: '(prefers-reduced-motion: reduce)',
    },
    (context) => {
      const introItems = page.querySelectorAll<HTMLElement>('[data-login-intro]')
      if (context.conditions?.reduceMotion === true) {
        gsap.set([card, ...introItems], { clearProps: 'all' })
        return undefined
      }

      const intro = gsap.timeline({ defaults: { ease: 'power3.out' } })
      intro
        .from(card, { y: 28, scale: 0.985, autoAlpha: 0, duration: 1.05 }, 0.08)
        .from(introItems, { y: 12, autoAlpha: 0, duration: 0.54, stagger: 0.045 }, 0.36)
      return () => intro.kill()
    },
    page,
  )
})

onBeforeUnmount(() => {
  introMedia?.revert()
  introMedia = null
  if (cardRef.value) gsap.killTweensOf(cardRef.value)
  if (statusRef.value) gsap.killTweensOf(statusRef.value)
})
</script>

<template>
  <main ref="pageRef" class="login-page" :data-api-mode="apiConfig.mode">
    <a class="login-skip-link" href="#nexus-login-form">跳到登录表单</a>
    <div class="login-grain" aria-hidden="true"></div>
    <div class="login-vignette" aria-hidden="true"></div>
    <KnowledgeStarMap ref="starMapRef" />

    <div class="login-auth-layout">
      <section class="login-auth-panel" aria-labelledby="login-title">
        <div ref="cardRef" class="login-card">
          <div class="login-product-mark" data-login-intro>
            <span class="login-product-symbol" aria-hidden="true">
              <i></i>
              <i></i>
              <i></i>
              <i></i>
            </span>
            <span class="login-product-copy">
              <strong>NEXUS RAG</strong>
              <small>PRIVATE KNOWLEDGE WORKSPACE / 01</small>
            </span>
          </div>

          <div class="login-card-heading" data-login-intro>
            <div class="login-kicker-row">
              <p>账户登录</p>
              <span v-if="loginModePresentation.badge" class="login-mode-badge">
                {{ loginModePresentation.badge }}
              </span>
            </div>
            <h1 id="login-title">欢迎回来</h1>
          </div>

          <form id="nexus-login-form" novalidate @submit.prevent="handleSubmit">
            <div class="login-field-group" data-login-intro>
              <label for="login-identity">用户名或邮箱</label>
              <input
                id="login-identity"
                v-model="identity"
                name="identity"
                type="text"
                inputmode="email"
                autocomplete="username"
                placeholder="name@example.com"
                maxlength="320"
                :aria-invalid="Boolean(identityError)"
                :aria-describedby="identityError ? 'login-identity-error' : undefined"
                @input="clearIdentityError"
                @focus="setKnowledgeFocus('identity', true)"
                @blur="setKnowledgeFocus('identity', false)"
              />
              <p
                v-if="identityError"
                id="login-identity-error"
                class="login-field-error"
              >
                {{ identityError }}
              </p>
            </div>

            <div class="login-field-group" data-login-intro>
              <label for="login-password">密码</label>
              <div class="login-password-field">
                <input
                  id="login-password"
                  ref="passwordInputRef"
                  v-model="password"
                  name="password"
                  :type="passwordType"
                  autocomplete="current-password"
                  placeholder="12–72 个 UTF-8 字节"
                  :aria-invalid="Boolean(passwordError)"
                  :aria-describedby="passwordError ? 'login-password-error' : undefined"
                  @input="clearPasswordError"
                  @focus="setKnowledgeFocus('security', true)"
                  @blur="setKnowledgeFocus('security', false)"
                />
                <button
                  class="login-password-toggle"
                  type="button"
                  :aria-label="passwordToggleLabel"
                  aria-controls="login-password"
                  :aria-pressed="showPassword"
                  @click="togglePassword"
                >
                  {{ showPassword ? '隐藏' : '显示' }}
                </button>
              </div>
              <p
                v-if="passwordError"
                id="login-password-error"
                class="login-field-error"
              >
                {{ passwordError }}
              </p>
            </div>

            <div class="login-session-meta" data-login-intro>
              <span class="login-session-mark" aria-hidden="true"></span>
              <span>安全会话</span>
              <span class="login-session-separator">/</span>
              <span>关闭标签页后退出</span>
            </div>

            <button
              class="login-submit-button"
              :class="{ 'is-submitting': isSubmitting }"
              type="submit"
              :disabled="isSubmitting"
              :aria-busy="isSubmitting"
              data-login-intro
            >
              <span>{{ isSubmitting ? '验证中…' : '登录' }}</span>
              <span class="login-submit-arrow" aria-hidden="true">↗</span>
            </button>

            <p
              v-if="formMessage"
              ref="statusRef"
              class="login-form-status"
              :class="`is-${formMessageKind}`"
              :role="formMessageKind === 'error' ? 'alert' : 'status'"
              aria-live="polite"
            >
              {{ formMessage }}
            </p>
          </form>

          <div class="login-security-boundary" data-login-intro>
            <span>安全边界</span>
            <div>
              <span class="login-passkey-mark" aria-hidden="true"></span>
              <strong>{{ loginModePresentation.securityMessage }}</strong>
            </div>
          </div>

          <div class="login-card-footer" data-login-intro>
            <template v-if="loginModePresentation.workspaceLinkLabel">
              <span>{{ loginModePresentation.footerLabel }}</span>
              <RouterLink to="/dashboard">
                {{ loginModePresentation.workspaceLinkLabel }}
              </RouterLink>
            </template>
            <template v-else>
              <span>{{ loginModePresentation.footerLabel }}</span>
              <strong>请联系系统管理员</strong>
            </template>
          </div>
        </div>
      </section>
    </div>
  </main>
</template>

<style scoped>
.login-page {
  position: relative;
  min-width: 320px;
  min-height: 100dvh;
  overflow: hidden;
  isolation: isolate;
  color-scheme: dark;
  background: #050505;
  color: #f4f4f4;
  font-family:
    'Segoe UI Variable Text', 'Microsoft YaHei UI', 'PingFang SC', sans-serif;
  font-synthesis: none;
}

.login-skip-link {
  position: fixed;
  top: 1rem;
  left: 1rem;
  z-index: 100;
  padding: 0.7rem 1rem;
  background: #fff;
  color: #050505;
  transform: translateY(-180%);
  transition: transform 180ms ease;
}

.login-skip-link:focus {
  transform: translateY(0);
}

.login-grain {
  position: fixed;
  z-index: 20;
  inset: 0;
  pointer-events: none;
  opacity: 0.1;
  mix-blend-mode: soft-light;
  background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 180 180' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='.92' numOctaves='3' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='.5'/%3E%3C/svg%3E");
}

.login-vignette {
  position: fixed;
  z-index: 3;
  inset: 0;
  pointer-events: none;
  box-shadow:
    inset -18vw 0 18vw 4vw #050505,
    inset 0 0 14rem 5rem rgba(5, 5, 5, 0.42);
}

.login-auth-layout {
  position: relative;
  z-index: 5;
  display: grid;
  min-height: 100dvh;
  padding: clamp(1.25rem, 4vw, 3rem) clamp(2rem, 10vw, 10rem);
  place-items: center end;
}

.login-auth-panel {
  width: min(100%, 28.5rem);
}

.login-card {
  position: relative;
  width: 100%;
  padding: clamp(2rem, 5vw, 3.2rem);
  border-left: 1px solid rgba(255, 255, 255, 0.2);
  background: rgba(5, 5, 5, 0.72);
  box-shadow:
    -2rem 2rem 8rem rgba(0, 0, 0, 0.46),
    inset 0 1px rgba(255, 255, 255, 0.035);
  backdrop-filter: blur(1.25rem);
  transform-origin: center;
  will-change: transform, opacity;
}

.login-card::before,
.login-card::after {
  position: absolute;
  width: 2.6rem;
  height: 2.6rem;
  pointer-events: none;
  content: '';
}

.login-card::before {
  top: 0;
  left: -1px;
  border-top: 1px solid rgba(255, 255, 255, 0.52);
  border-left: 1px solid rgba(255, 255, 255, 0.52);
}

.login-card::after {
  right: 0;
  bottom: 0;
  border-right: 1px solid rgba(255, 255, 255, 0.22);
  border-bottom: 1px solid rgba(255, 255, 255, 0.22);
}

.login-product-mark {
  display: flex;
  align-items: center;
  gap: 0.85rem;
  margin-bottom: clamp(3.5rem, 8vh, 5.6rem);
}

.login-product-symbol {
  position: relative;
  display: block;
  width: 1.8rem;
  height: 1.8rem;
}

.login-product-symbol::before,
.login-product-symbol::after {
  position: absolute;
  background: rgba(255, 255, 255, 0.34);
  content: '';
  transform-origin: left center;
}

.login-product-symbol::before {
  top: 0.48rem;
  left: 0.42rem;
  width: 1rem;
  height: 1px;
  transform: rotate(34deg);
}

.login-product-symbol::after {
  top: 1.28rem;
  left: 0.4rem;
  width: 1.05rem;
  height: 1px;
  transform: rotate(-28deg);
}

.login-product-symbol i {
  position: absolute;
  width: 0.34rem;
  height: 0.34rem;
  border: 1px solid #fff;
  border-radius: 50%;
  background: #050505;
}

.login-product-symbol i:nth-child(1) {
  top: 0.15rem;
  left: 0.2rem;
}

.login-product-symbol i:nth-child(2) {
  top: 0.5rem;
  right: 0.12rem;
}

.login-product-symbol i:nth-child(3) {
  bottom: 0.12rem;
  left: 0.12rem;
}

.login-product-symbol i:nth-child(4) {
  right: 0.15rem;
  bottom: 0.34rem;
}

.login-product-copy {
  display: grid;
  gap: 0.2rem;
}

.login-product-copy strong,
.login-product-copy small {
  font-family: Consolas, 'SFMono-Regular', monospace;
  letter-spacing: 0.16em;
}

.login-product-copy strong {
  color: #e8e8e8;
  font-size: 0.64rem;
  font-weight: 700;
}

.login-product-copy small {
  color: #656565;
  font-size: 0.52rem;
}

.login-kicker-row {
  display: flex;
  min-height: 1rem;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  margin-bottom: 0.72rem;
}

.login-kicker-row p {
  margin: 0;
  color: #969696;
  font-size: 0.67rem;
  font-weight: 700;
  letter-spacing: 0.12em;
}

.login-mode-badge {
  padding: 0.18rem 0.34rem;
  border: 1px solid rgba(255, 255, 255, 0.22);
  color: #a4a4a4;
  font-family: Consolas, 'SFMono-Regular', monospace;
  font-size: 0.48rem;
  letter-spacing: 0.13em;
}

.login-card-heading h1 {
  margin: 0;
  font-family: 'Segoe UI Variable Display', 'Microsoft YaHei UI', sans-serif;
  font-size: clamp(2.65rem, 6vw, 3.55rem);
  font-weight: 610;
  letter-spacing: -0.06em;
  line-height: 1;
}

.login-field-group {
  position: relative;
  margin-top: 2.25rem;
}

.login-field-group label {
  display: block;
  margin-bottom: 0.52rem;
  color: #b6b6b6;
  font-size: 0.68rem;
  font-weight: 700;
  letter-spacing: 0.07em;
}

.login-field-group input {
  width: 100%;
  height: 3.5rem;
  padding: 0 0.15rem;
  border: 0;
  border-bottom: 1px solid #444444;
  border-radius: 0;
  outline: 0;
  background: transparent;
  color: #f4f4f4;
  font-size: 0.94rem;
  caret-color: #fff;
  transition:
    border-color 180ms ease,
    background-color 180ms ease;
}

.login-field-group input::placeholder {
  color: #616161;
}

.login-field-group input:focus {
  border-bottom-color: #fff;
  background: rgba(255, 255, 255, 0.035);
}

.login-field-group input[aria-invalid='true'] {
  border-bottom-color: #cfcfcf;
}

.login-field-group input:-webkit-autofill,
.login-field-group input:-webkit-autofill:hover,
.login-field-group input:-webkit-autofill:focus {
  border-bottom-color: #777777;
  -webkit-text-fill-color: #f4f4f4;
  box-shadow: 0 0 0 1000px #080808 inset;
  caret-color: #fff;
}

.login-password-field {
  position: relative;
}

.login-password-field input {
  padding-right: 3.5rem;
}

.login-password-toggle {
  position: absolute;
  top: 50%;
  right: 0;
  padding: 0.4rem;
  border: 0;
  background: transparent;
  color: #a4a4a4;
  font-size: 0.66rem;
  font-weight: 700;
  cursor: pointer;
  transform: translateY(-50%);
}

.login-field-error {
  margin: 0.45rem 0 0;
  color: #cfcfcf;
  font-size: 0.66rem;
  line-height: 1.45;
}

.login-session-meta {
  display: flex;
  align-items: center;
  gap: 0.48rem;
  margin: 1.35rem 0 1.7rem;
  color: #8b8b8b;
  font-size: 0.66rem;
  font-weight: 650;
}

.login-session-mark {
  display: block;
  width: 0.8rem;
  height: 0.8rem;
  border: 1px solid #777777;
  border-radius: 50%;
  box-shadow: inset 0 0 0 2px #050505;
  background: #d7d7d7;
}

.login-session-separator {
  color: #454545;
}

.login-submit-button {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  min-height: 3.65rem;
  padding: 0 1.25rem;
  overflow: hidden;
  border: 1px solid #fff;
  background: #fff;
  color: #050505;
  font-size: 0.72rem;
  font-weight: 750;
  letter-spacing: 0.1em;
  cursor: pointer;
  transition:
    color 180ms ease,
    opacity 180ms ease;
}

.login-submit-button::before {
  position: absolute;
  inset: 0;
  background: #151515;
  content: '';
  transform: translateX(-102%);
  transition: transform 420ms cubic-bezier(0.16, 1, 0.3, 1);
}

.login-submit-button:hover:not(:disabled) {
  color: #fff;
}

.login-submit-button:hover:not(:disabled)::before {
  transform: translateX(0);
}

.login-submit-button:disabled {
  cursor: wait;
  opacity: 0.72;
}

.login-submit-button > span {
  position: relative;
  z-index: 1;
}

.login-submit-arrow {
  font-size: 1.05rem;
  transition: transform 220ms ease;
}

.login-submit-button.is-submitting .login-submit-arrow {
  transform: rotate(45deg) scale(0.8);
}

.login-form-status {
  margin: 0.8rem 0 0;
  padding-left: 0.65rem;
  border-left: 1px solid currentColor;
  font-size: 0.68rem;
  line-height: 1.55;
}

.login-form-status.is-error {
  color: #cfcfcf;
}

.login-form-status.is-info {
  color: #bdbdbd;
}

.login-security-boundary {
  position: relative;
  margin-top: 1.35rem;
  padding-top: 1.55rem;
  border-top: 1px solid #353535;
  text-align: center;
}

.login-security-boundary > span {
  position: absolute;
  top: -0.45rem;
  left: 50%;
  padding: 0 0.7rem;
  background: #080808;
  color: #707070;
  font-size: 0.58rem;
  transform: translateX(-50%);
}

.login-security-boundary > div {
  display: inline-flex;
  min-height: 2.75rem;
  align-items: center;
  justify-content: center;
  gap: 0.68rem;
  color: #c9c9c9;
}

.login-security-boundary strong {
  font-size: 0.67rem;
  font-weight: 700;
}

.login-passkey-mark {
  position: relative;
  width: 1.05rem;
  height: 1.05rem;
  border: 1.5px solid currentColor;
  border-radius: 50%;
}

.login-passkey-mark::after {
  position: absolute;
  top: 50%;
  left: 100%;
  width: 0.48rem;
  height: 1.5px;
  background: currentColor;
  content: '';
}

.login-card-footer {
  display: flex;
  justify-content: center;
  gap: 0.65rem;
  margin-top: 1.15rem;
  color: #777777;
  font-size: 0.67rem;
}

.login-card-footer a,
.login-card-footer strong {
  color: #d7d7d7;
  font-weight: 700;
}

.login-card-footer a {
  border-bottom: 1px solid currentColor;
}

.login-page button:focus-visible,
.login-page a:focus-visible,
.login-page input:focus-visible {
  outline: 2px solid #fff;
  outline-offset: 3px;
}

@media (min-width: 761px) and (max-height: 820px) {
  .login-auth-layout {
    padding-block: 1.25rem;
  }

  .login-card {
    padding-block: 1.8rem;
  }

  .login-product-mark {
    margin-bottom: 2.35rem;
  }

  .login-card-heading h1 {
    font-size: 3rem;
  }

  .login-field-group {
    margin-top: 1.45rem;
  }

  .login-session-meta {
    margin: 1rem 0 1.35rem;
  }

  .login-security-boundary {
    padding-top: 1.25rem;
  }

  .login-card-footer {
    margin-top: 0.85rem;
  }
}

@media (max-width: 760px) {
  .login-page {
    overflow-y: auto;
  }

  .login-auth-layout {
    padding: 1rem;
    place-items: center;
  }

  .login-card {
    padding: 2.25rem 1.4rem;
    background: rgba(6, 6, 6, 0.88);
    backdrop-filter: blur(1.15rem);
  }

  .login-product-mark {
    margin-bottom: 3.8rem;
  }

  .login-vignette {
    box-shadow:
      inset 0 -16rem 12rem -4rem #050505,
      inset 0 0 9rem 2rem rgba(5, 5, 5, 0.46);
  }
}

@media (max-width: 420px) {
  .login-auth-layout {
    align-items: start;
    padding-top: 1rem;
  }

  .login-card {
    min-height: calc(100dvh - 2rem);
  }

  .login-product-mark {
    margin-bottom: 3.1rem;
  }

  .login-session-meta {
    flex-wrap: wrap;
  }
}

@media (prefers-reduced-motion: reduce) {
  .login-card {
    will-change: auto;
  }
}
</style>
