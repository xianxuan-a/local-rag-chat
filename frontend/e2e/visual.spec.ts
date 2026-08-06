import path from 'node:path'

import { expect, test } from '@playwright/test'

const pages = [
  ['dashboard', '/dashboard'],
  ['chat', '/chat'],
  ['files', '/files'],
  ['indexes', '/indexes'],
  ['settings', '/settings'],
] as const

const viewports = [
  { width: 1024, height: 768 },
  { width: 1440, height: 900 },
  { width: 1920, height: 1080 },
] as const

test('capture the 15 visual QA reference screenshots', async ({ page }) => {
  const consoleProblems: string[] = []
  page.on('pageerror', (error) => consoleProblems.push(error.message))
  page.on('console', (message) => {
    if (message.type() === 'error' || message.text().includes('[Vue warn]')) {
      consoleProblems.push(message.text())
    }
  })

  for (const viewport of viewports) {
    await page.setViewportSize(viewport)
    for (const [name, route] of pages) {
      await page.goto(route)
      await expect(page.locator('.page')).toBeVisible()
      if (name === 'dashboard') {
        await expect(page.locator('.metric-card')).toHaveCount(6)
        await expect(page.locator('canvas')).toHaveCount(2)
      } else if (name === 'chat') {
        await expect(page.locator('article.message')).toHaveCount(4)
        await expect(page.locator('.chat-side-right .source-card')).toHaveCount(3)
      } else if (name === 'files') {
        await expect(page.getByText('损坏的技术文档.pdf').first()).toBeVisible()
      } else if (name === 'indexes') {
        await expect(page.getByText('kb_product_active_g12').first()).toBeVisible()
      } else {
        await expect(page.getByLabel('默认 TopK')).toHaveValue('5')
      }
      await page.waitForTimeout(120)
      const overflow = await page.evaluate(
        () =>
          document.documentElement.scrollWidth - document.documentElement.clientWidth,
      )
      expect(overflow).toBeLessThanOrEqual(1)
      await page.screenshot({
        path: path.resolve(
          'artifacts',
          'visual-qa',
          `${name}-${viewport.width}x${viewport.height}.png`,
        ),
        fullPage: false,
      })
    }
  }

  expect(consoleProblems).toEqual([])
})
