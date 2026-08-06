import { expect, test } from '@playwright/test'

const runRealBoundary = process.env.NEXUS_REAL_BOUNDARY_E2E === '1'

test.describe('Real authentication boundary', () => {
  test.skip(!runRealBoundary, 'Real-mode preview is required')

  test('guards a business route and reports an invalid or unreachable login', async ({
    page,
  }) => {
    await page.addInitScript(() => {
      // Playwright serializes this callback into the browser context.
      // eslint-disable-next-line @typescript-eslint/no-unsafe-call
      window.sessionStorage.clear()
    })

    await page.goto('/knowledge-bases')
    await expect(page).toHaveURL(/\/login\?redirect=(?:%2F|\/)knowledge-bases$/u)
    await expect(page.getByText('MOCK MODE', { exact: true })).toHaveCount(0)

    await page.getByLabel('用户名或邮箱').fill('codex-nonexistent-account')
    await page.getByLabel('密码', { exact: true }).fill('not-a-real-password')
    await page.getByRole('button', { name: '登录', exact: true }).click()

    await expect(page).toHaveURL(/\/login\?redirect=/u)
    await expect(page.getByRole('alert')).toContainText(
      /用户名、邮箱或密码不正确|后端服务不可达|认证服务暂时不可用/u,
    )
  })
})
