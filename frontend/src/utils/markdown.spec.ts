import { describe, expect, it } from 'vitest'

import { renderMarkdown } from '@/utils/markdown'

describe('renderMarkdown', () => {
  it('renders supported markdown and secures external links', () => {
    const html = renderMarkdown('**重点** [官方文档](https://example.com) `TopK`')
    const root = document.createElement('div')
    root.innerHTML = html
    expect(root.querySelector('strong')?.textContent).toBe('重点')
    expect(root.querySelector('code')?.textContent).toBe('TopK')
    expect(root.querySelector('a')?.target).toBe('_blank')
    expect(root.querySelector('a')?.rel).toBe('noopener noreferrer')
  })

  it('does not create executable raw HTML', () => {
    const html = renderMarkdown(
      '<script>window.__unsafe = true</script><img src=x onerror=alert(1)>',
    )
    const root = document.createElement('div')
    root.innerHTML = html
    expect(root.querySelector('script')).toBeNull()
    expect(root.querySelector('img')).toBeNull()
    expect(window).not.toHaveProperty('__unsafe')
  })
})
