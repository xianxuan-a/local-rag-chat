import path from 'node:path'

import { expect, test } from '@playwright/test'

test('validates the isolated Mock login boundary on desktop and mobile', async ({
  page,
}) => {
  const consoleProblems: string[] = []
  page.on('pageerror', (error) => consoleProblems.push(error.message))
  page.on('console', (message) => {
    if (message.type() === 'error' || message.text().includes('[Vue warn]')) {
      consoleProblems.push(message.text())
    }
  })

  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto('/login')
  await expect(page.getByRole('heading', { name: '欢迎回来' })).toBeVisible()
  await expect(page.getByText('MOCK MODE', { exact: true })).toBeVisible()

  await page.mouse.move(0, 0)
  await page.screenshot({
    path: path.resolve('artifacts', 'visual-qa', 'login-1440x900.png'),
    fullPage: false,
  })

  await page.getByRole('button', { name: '登录', exact: true }).click()
  await expect(page.getByText('请输入用户名或邮箱。')).toBeVisible()
  await expect(page.getByText('请输入密码。')).toBeVisible()

  await page.getByLabel('用户名或邮箱').fill('local-user')
  await page.getByLabel('密码', { exact: true }).fill('twelve-bytes!')
  await page.getByRole('button', { name: '显示密码' }).click()
  await expect(page.getByLabel('密码', { exact: true })).toHaveAttribute('type', 'text')
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await expect(page.getByRole('status')).toContainText('Mock 模式不执行身份认证')

  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/login')
  await expect(page.getByRole('button', { name: '登录', exact: true })).toBeVisible()
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    ),
  ).toBeLessThanOrEqual(1)
  await page.screenshot({
    path: path.resolve('artifacts', 'visual-qa', 'login-390x844.png'),
    fullPage: true,
  })

  await page.goto('/dashboard')
  await expect(page.locator('.page')).toBeVisible()
  await expect(page.locator('.login-page')).toHaveCount(0)
  expect(consoleProblems).toEqual([])
})
