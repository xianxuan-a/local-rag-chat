import { createPinia } from 'pinia'
import { mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import router from '@/router'
import { useAuthStore } from '@/stores/auth'
import LoginView from '@/views/LoginView.vue'

vi.mock('@/api/loginMode', () => ({
  loginModePresentation: {
    isMock: false,
    badge: null,
    submitMessage: null,
    securityMessage: '凭据仅发送至本地认证服务',
    footerLabel: '需要账户？',
    workspaceLinkLabel: null,
  },
}))

function matchMedia(): MediaQueryList {
  return {
    matches: true,
    media: '(prefers-reduced-motion: reduce)',
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(() => true),
  }
}

async function mountRegistration(): Promise<{
  wrapper: VueWrapper
  register: ReturnType<typeof vi.spyOn>
  replace: ReturnType<typeof vi.spyOn>
}> {
  const pinia = createPinia()
  const register = vi.spyOn(useAuthStore(pinia), 'register').mockResolvedValue()
  await router.push('/login')
  await router.isReady()
  const replace = vi.spyOn(router, 'replace').mockResolvedValue()
  const wrapper = mount(LoginView, {
    attachTo: document.body,
    global: {
      plugins: [pinia, router],
      stubs: {
        KnowledgeStarMap: {
          template: '<div class="star-map-stub" />',
          methods: {
            setFocus: vi.fn(),
            capture: vi.fn(),
            restore: vi.fn(),
          },
        },
      },
    },
  })
  await wrapper.get('button.login-footer-action').trigger('click')
  return { wrapper, register, replace }
}

beforeEach(() => {
  vi.stubGlobal(
    'matchMedia',
    vi.fn(() => matchMedia()),
  )
})

afterEach(() => {
  document.body.innerHTML = ''
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('LoginView registration mode', () => {
  it('shows registration fields and enforces password and confirmation rules', async () => {
    const { wrapper, register } = await mountRegistration()

    expect(wrapper.get('h1').text()).toBe('创建账户')
    await wrapper.get('#login-identity').setValue('new-user')
    await wrapper.get('#register-email').setValue('new-user@example.com')
    await wrapper.get('#login-password').setValue('1234567')
    await wrapper.get('#register-password-confirmation').setValue('different')
    await wrapper.get('form').trigger('submit')

    expect(wrapper.get('#login-password-error').text()).toBe('密码至少需要 8 个字符。')
    expect(wrapper.get('#register-password-confirmation-error').text()).toBe(
      '两次输入的密码不一致。',
    )
    expect(register).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('submits a valid eight-character registration and redirects', async () => {
    const { wrapper, register, replace } = await mountRegistration()

    await wrapper.get('#login-identity').setValue('new-user')
    await wrapper.get('#register-email').setValue('new-user@example.com')
    await wrapper.get('#login-password').setValue('pass1234')
    await wrapper.get('#register-password-confirmation').setValue('pass1234')
    await wrapper.get('form').trigger('submit')
    await vi.waitFor(() => {
      expect(register).toHaveBeenCalledWith(
        'new-user',
        'new-user@example.com',
        'pass1234',
      )
    })
    expect(replace).toHaveBeenCalledWith('/dashboard')
    wrapper.unmount()
  })
})
