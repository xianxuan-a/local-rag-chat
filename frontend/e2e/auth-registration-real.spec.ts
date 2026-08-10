import { expect, test } from '@playwright/test'

const runRealRegistration = process.env.NEXUS_REAL_REGISTRATION_E2E === '1'
const username = process.env.NEXUS_REAL_REGISTRATION_USERNAME ?? ''
const email = username ? `${username}@example.com` : ''
const password = 'pass1234'

test.describe('Real account registration', () => {
  test.skip(
    !runRealRegistration || !username,
    'registration-enabled Real API environment is required',
  )

  test('validates, registers, automatically signs in and persists the account', async ({
    page,
  }) => {
    await page.addInitScript(() => {
      // Playwright serializes this callback into the browser context.
      // eslint-disable-next-line @typescript-eslint/no-unsafe-call
      window.sessionStorage.clear()
    })
    await page.goto('/login')
    await page.getByRole('button', { name: '注册账户' }).click()
    await expect(page.getByRole('heading', { name: '创建账户' })).toBeVisible()

    await page.getByLabel('用户名', { exact: true }).fill(username)
    await page.getByLabel('邮箱（可选）').fill(email)
    await page.getByLabel('密码', { exact: true }).fill('1234567')
    await page.getByLabel('确认密码').fill('different')
    await page.getByRole('button', { name: '注册并登录' }).click()
    await expect(page.getByText('密码至少需要 8 个字符。')).toBeVisible()
    await expect(page.getByText('两次输入的密码不一致。')).toBeVisible()

    await page.getByLabel('密码', { exact: true }).fill(password)
    await page.getByLabel('确认密码').fill(password)
    await page.getByRole('button', { name: '注册并登录' }).click()
    await expect(page).toHaveURL(/\/dashboard$/u)
    await expect(page.getByText(username, { exact: true })).toBeVisible()

    await page.getByRole('button', { name: '退出登录' }).click()
    await expect(page).toHaveURL(/\/login$/u)
    await page.getByLabel('用户名或邮箱').fill(email)
    await page.getByLabel('密码', { exact: true }).fill(password)
    await page.getByRole('button', { name: '登录', exact: true }).click()
    await expect(page).toHaveURL(/\/dashboard$/u)
    await expect(page.getByText(username, { exact: true })).toBeVisible()
  })
})
