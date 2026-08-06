import { createPinia } from 'pinia'
import { mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import router from '@/router'
import LoginView from '@/views/LoginView.vue'

function matchMedia(matches: boolean): MediaQueryList {
  return {
    matches,
    media: '(prefers-reduced-motion: reduce)',
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(() => true),
  }
}

async function mountLogin(): Promise<VueWrapper> {
  await router.push('/login')
  await router.isReady()
  return mount(LoginView, {
    attachTo: document.body,
    global: {
      plugins: [createPinia(), router],
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
}

beforeEach(() => {
  vi.stubGlobal(
    'matchMedia',
    vi.fn(() => matchMedia(true)),
  )
})

afterEach(() => {
  document.body.innerHTML = ''
  vi.unstubAllGlobals()
})

describe('LoginView', () => {
  it('shows accessible field errors for an empty submission', async () => {
    const wrapper = await mountLogin()

    await wrapper.get('form').trigger('submit')

    expect(wrapper.get('#login-identity-error').text()).toBe('请输入用户名或邮箱。')
    expect(wrapper.get('#login-password-error').text()).toBe('请输入密码。')
    expect(wrapper.get('#login-identity').attributes('aria-invalid')).toBe('true')
    wrapper.unmount()
  })

  it('toggles password visibility and never authenticates in Mock mode', async () => {
    const wrapper = await mountLogin()
    const password = wrapper.get<HTMLInputElement>('#login-password')

    await wrapper.get('#login-identity').setValue('local-user')
    await password.setValue('twelve-bytes!')
    await wrapper.get('button[aria-label="显示密码"]').trigger('click')
    expect(password.element.type).toBe('text')

    await wrapper.get('form').trigger('submit')

    expect(wrapper.get('[role="status"]').text()).toContain('Mock 模式不执行身份认证')
    expect(window.sessionStorage.length).toBe(0)
    wrapper.unmount()
  })
})
