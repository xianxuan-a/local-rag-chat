import { expect, test } from '@playwright/test'

const identity = process.env.NEXUS_REAL_API_IDENTITY ?? ''
const password = process.env.NEXUS_REAL_API_PASSWORD ?? ''
const runRealAuth = process.env.NEXUS_REAL_AUTH_E2E === '1'

test.describe('Real API authentication', () => {
  test.skip(
    !runRealAuth || !identity || !password,
    'Real API login credentials are required',
  )

  test('guards protected routes, logs in, restores the redirect and logs out', async ({
    page,
  }) => {
    await page.addInitScript(() => {
      // Playwright serializes this callback into the browser context.
      // eslint-disable-next-line @typescript-eslint/no-unsafe-call
      window.sessionStorage.clear()
    })
    await page.goto('/knowledge-bases')
    await expect(page).toHaveURL(/\/login\?redirect=(?:%2F|\/)knowledge-bases$/u)
    await page.screenshot({
      path: 'artifacts/visual-qa/login-1440x900.png',
      fullPage: true,
    })

    await page.getByLabel('用户名或邮箱').fill(identity)
    await page.getByLabel('密码', { exact: true }).fill(password)
    await page.getByRole('button', { name: '登录', exact: true }).click()

    await expect(page).toHaveURL(/\/knowledge-bases$/u)
    await expect(page.getByText(identity, { exact: true })).toBeVisible()
    await expect(page.getByRole('button', { name: '退出登录' })).toBeVisible()

    await page.getByRole('button', { name: '退出登录' }).click()
    await expect(page).toHaveURL(/\/login$/u)
    await expect(page.getByRole('heading', { name: '欢迎回来' })).toBeVisible()
    await page.goto('/knowledge-bases')
    await expect(page).toHaveURL(/\/login\?redirect=(?:%2F|\/)knowledge-bases$/u)
  })
})
