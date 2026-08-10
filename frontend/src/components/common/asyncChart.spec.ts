import { flushPromises, mount } from '@vue/test-utils'
import { h, type Component } from 'vue'
import { describe, expect, it, vi } from 'vitest'

import { createAsyncChartComponent } from '@/components/common/asyncChart'

function mountAsyncChart(component: Component) {
  const Host: Component = {
    setup() {
      return () => h(component, { option: {}, ariaLabel: '活动趋势' })
    },
  }
  return mount(Host)
}

describe('async Dashboard chart boundary', () => {
  it('shows an accessible loading state and then renders the chart', async () => {
    let resolveLoader: ((component: Component) => void) | undefined
    const loader = vi.fn(
      () =>
        new Promise<Component>((resolve) => {
          resolveLoader = resolve
        }),
    )
    const LoadedChart: Component = {
      inheritAttrs: false,
      setup() {
        return () => h('div', { 'data-testid': 'loaded-chart' }, 'loaded')
      },
    }
    const AsyncChart = createAsyncChartComponent(loader)
    const wrapper = mountAsyncChart(AsyncChart)

    expect(wrapper.get('[role="status"]').attributes('aria-busy')).toBe('true')
    if (!resolveLoader) throw new Error('async chart loader was not called')
    resolveLoader(LoadedChart)
    await flushPromises()
    await vi.waitFor(() => {
      expect(
        wrapper.find('[data-testid="loaded-chart"]').exists(),
        wrapper.html(),
      ).toBe(true)
    })

    expect(wrapper.get('[data-testid="loaded-chart"]').text()).toBe('loaded')
    expect(loader).toHaveBeenCalledTimes(1)
  })

  it('retries one failed chunk request and exposes an error boundary', async () => {
    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => undefined)
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => undefined)
    const loader = vi.fn(() => Promise.reject(new Error('chunk unavailable')))
    const AsyncChart = createAsyncChartComponent(loader)
    const wrapper = mountAsyncChart(AsyncChart)

    await flushPromises()
    await flushPromises()
    await vi.waitFor(() => {
      expect(wrapper.find('[role="alert"]').exists(), wrapper.html()).toBe(true)
    })

    expect(loader).toHaveBeenCalledTimes(2)
    expect(wrapper.get('[role="alert"]').text()).toContain('图表组件加载失败')
    errorSpy.mockRestore()
    warnSpy.mockRestore()
  })
})
