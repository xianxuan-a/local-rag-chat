import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import StatusBadge from '@/components/common/StatusBadge.vue'

describe('StatusBadge', () => {
  it.each([
    ['SUCCESS', '状态：成功'],
    ['FAILED', '状态：失败'],
    ['BUILDING', '状态：构建中'],
    ['DRAFT', '状态：草稿'],
  ])('exposes an accessible name for %s', (status, accessibleName) => {
    const wrapper = mount(StatusBadge, { props: { status } })
    expect(wrapper.attributes('aria-label')).toBe(accessibleName)
    expect(wrapper.text().length).toBeGreaterThan(0)
  })
})
