import { expect, test } from '@playwright/test'

const accessToken = process.env.NEXUS_REAL_API_ACCESS_TOKEN ?? ''
const runRealApi = process.env.NEXUS_REAL_API_E2E === '1'
const expectBackendDown = process.env.NEXUS_EXPECT_BACKEND_DOWN === '1'
const uniqueName = process.env.NEXUS_REAL_API_KB_NAME ?? `codex-real-api-${Date.now()}`
const retrievalRunName = `Real 检索评测 ${uniqueName}`
const ragRunName = `Real RAG 评测 ${uniqueName}`
const datasetName = `Real 数据集 ${uniqueName}`

test.describe('Real API phase one', () => {
  test.skip(!runRealApi || !accessToken, 'isolated Real API environment is required')

  test.beforeEach(async ({ page }) => {
    await page.addInitScript(
      ({ key, token }: { key: string; token: string }) => {
        // Playwright serializes this callback into the browser context.
        // eslint-disable-next-line @typescript-eslint/no-unsafe-call
        window.sessionStorage.setItem(key, token)
      },
      { key: 'nexus-rag-access-token', token: accessToken },
    )
  })

  test('persists knowledge bases and files through real FastAPI requests', async ({
    page,
  }) => {
    test.setTimeout(150_000)
    test.skip(expectBackendDown, 'backend-down pass is separate')
    const consoleErrors: string[] = []
    const failedRequests: string[] = []
    const network: string[] = []
    page.on('console', (message) => {
      if (message.type() === 'error') consoleErrors.push(message.text())
    })
    page.on('response', (response) => {
      if (response.url().includes('/api/')) {
        network.push(
          `${response.request().method()} ${new URL(response.url()).pathname} ${response.status()}`,
        )
      }
    })
    page.on('requestfailed', (request) => {
      failedRequests.push(
        `${request.method()} ${request.url()} ${request.failure()?.errorText ?? 'failed'}`,
      )
    })

    await page.goto('/settings')
    await expect(page.getByRole('heading', { name: '系统设置' })).toBeVisible()
    await page.getByRole('spinbutton', { name: '默认 TopK' }).fill('6')
    await page.getByRole('button', { name: '保存设置' }).click()
    await expect(page.getByText('服务器设置已保存并重新读取')).toBeVisible()
    await page.reload()
    await expect(page.getByRole('spinbutton', { name: '默认 TopK' })).toHaveValue('6')

    await page.getByRole('link', { name: '知识库' }).click()
    await expect(page.getByText('产品知识中台')).toHaveCount(0)
    await page.getByRole('button', { name: '新建知识库' }).first().click()
    await page.locator('#kb-name').fill(uniqueName)
    await page.locator('#kb-description').fill('Real API browser integration')
    await page.getByRole('button', { name: '创建知识库' }).click()
    await page.waitForTimeout(500)
    const formError = page.locator('.form-error')
    if (await formError.isVisible()) {
      throw new Error(
        `Create failed: ${await formError.textContent()}; requests=${failedRequests.join(' | ')}; console=${consoleErrors.join(' | ')}`,
      )
    }
    await expect(
      page.locator('article.kb-card').filter({ hasText: uniqueName }),
    ).toBeVisible()
    let card = page.locator('article.kb-card').filter({ hasText: uniqueName })
    await card.getByRole('button', { name: '编辑知识库' }).click()
    await page.locator('#kb-description').fill('Real API browser integration（已编辑）')
    await page.getByRole('button', { name: '保存修改' }).click()
    await expect(card).toContainText('已编辑')

    await page.reload()
    card = page.locator('article.kb-card').filter({ hasText: uniqueName })
    await expect(card).toBeVisible()
    await expect(card).toContainText('已编辑')
    await card.getByRole('button', { name: '打开' }).click()

    await page.getByRole('button', { name: '上传文件' }).first().click()
    await page.locator('input[type="file"]').setInputFiles({
      name: 'real-api-document.txt',
      mimeType: 'text/plain',
      buffer: Buffer.from('Real API persistence and processing evidence.'),
    })
    await page.getByRole('button', { name: '加入处理队列' }).click()
    let row = page.locator('tr').filter({ hasText: 'real-api-document.txt' })
    await expect(row.getByLabel('状态：等待中')).toBeVisible()
    await page.reload()
    row = page.locator('tr').filter({ hasText: 'real-api-document.txt' })
    await expect(row).toBeVisible()
    await row.getByRole('button', { name: '处理文件' }).click()
    await expect(row.getByLabel('状态：成功')).toBeVisible({ timeout: 15_000 })
    await expect(row).toContainText('1')

    await page.reload()
    row = page.locator('tr').filter({ hasText: 'real-api-document.txt' })
    await expect(row.getByLabel('状态：成功')).toBeVisible()
    await page.getByRole('link', { name: '检索测试' }).click()
    await page.locator('#retrieval-query').fill('persistence evidence')
    await page.getByRole('button', { name: '执行检索' }).first().click()
    await expect(
      page.locator('.result-file').filter({ hasText: 'real-api-document.txt' }),
    ).toBeVisible()
    await expect(
      page.getByText('Real API persistence and processing evidence.'),
    ).toBeVisible()

    await page.getByRole('link', { name: '智能问答' }).click()
    await expect(page.getByRole('heading', { name: '智能问答' })).toBeVisible()
    await page.getByRole('combobox', { name: '当前知识库' }).last().selectOption({
      label: uniqueName,
    })
    const [createSessionResponse] = await Promise.all([
      page.waitForResponse(
        (response) =>
          new URL(response.url()).pathname === '/api/sessions' &&
          response.request().method() === 'POST' &&
          response.status() === 201,
      ),
      page.getByRole('button', { name: '新建会话' }).first().click(),
    ])
    const createdSessionEnvelope = (await createSessionResponse.json()) as {
      data?: { id?: string }
    }
    const createdSessionId = createdSessionEnvelope.data?.id
    expect(createdSessionId).toBeTruthy()
    await expect(page).toHaveURL(
      new RegExp(`/chat\\?sessionId=${createdSessionId as string}$`, 'u'),
    )
    const sessionUrl = page.url()
    const composer = page.getByLabel('输入问题')
    await composer.fill('请引用真实文档回答')
    await page.getByRole('button', { name: '发送问题' }).click()
    const firstAnswer = page
      .locator('.message:not(.message-user)')
      .filter({ hasText: '隔离环境中的确定性回答' })
      .last()
    await expect(firstAnswer).toBeVisible({ timeout: 15_000 })
    await expect(page.locator('.chat-side-right .source-card')).toHaveCount(1)
    const like = firstAnswer.getByRole('button', { name: '点赞回答' })
    await like.click()
    await expect(like).toHaveClass(/button-default/u)

    await page.reload()
    await expect(page).toHaveURL(sessionUrl)
    await expect(page.getByText('隔离环境中的确定性回答 [S1]').last()).toBeVisible()
    const restoredAnswer = page
      .locator('.message:not(.message-user)')
      .filter({ hasText: '隔离环境中的确定性回答' })
      .last()
    await expect(restoredAnswer.getByRole('button', { name: '点赞回答' })).toHaveClass(
      /button-default/u,
    )
    await restoredAnswer.getByRole('button', { name: '重新生成' }).click()
    await expect(page.getByText('生成中')).toBeVisible()
    await expect(page.getByText('生成完成')).toBeVisible({ timeout: 15_000 })
    await expect(
      page
        .locator('.message:not(.message-user)')
        .filter({ hasText: '隔离环境中的确定性回答' }),
    ).toHaveCount(1)

    await composer.fill('请生成一段可以停止的回答')
    await page.getByRole('button', { name: '发送问题' }).click()
    await expect(page.getByRole('button', { name: '停止生成' })).toBeVisible()
    await page.waitForTimeout(450)
    await page.getByRole('button', { name: '停止生成' }).click()
    await expect(page.getByText('已停止生成').last()).toBeVisible({
      timeout: 15_000,
    })

    await composer.fill('触发模型失败')
    await page.getByRole('button', { name: '发送问题' }).click()
    await expect(page.getByText('模型请求失败').last()).toBeVisible({
      timeout: 15_000,
    })

    await page.getByRole('link', { name: '会话历史' }).click()
    await page.getByRole('button', { name: '编辑会话标题' }).click()
    const titleInput = page.getByRole('textbox', { name: '会话标题' })
    await titleInput.fill('Real Chat 闭环')
    await page.getByRole('button', { name: '保存会话标题' }).click()
    await expect(page.getByText('Real Chat 闭环').first()).toBeVisible()
    await page.reload()
    await expect(page.getByText('Real Chat 闭环').first()).toBeVisible()
    await page.getByRole('button', { name: '删除当前会话' }).click()
    await page.getByRole('button', { name: '确认删除' }).click()
    await expect(page.getByText('Real Chat 闭环')).toHaveCount(0)

    await page.getByRole('link', { name: '索引管理' }).click()
    await page.getByRole('combobox', { name: '当前知识库' }).last().selectOption({
      label: uniqueName,
    })
    await page.getByRole('button', { name: '重建索引' }).click()
    await expect(page.getByText('索引重建已提交')).toBeVisible()
    const maintenance = page.locator('section.card').filter({
      hasText: '最近维护 Job',
    })
    await expect(maintenance.getByLabel('状态：成功')).toBeVisible({
      timeout: 20_000,
    })
    const rollbackRow = page.locator('tr').filter({
      has: page.getByRole('button', { name: '回滚索引' }),
    })
    await expect(rollbackRow).toBeVisible()
    page.once('dialog', (dialog) => dialog.accept())
    await rollbackRow.getByRole('button', { name: '回滚索引' }).click()
    await expect(page.getByText('已回滚到上一版本索引')).toBeVisible()
    const cleanupRow = page.locator('tr').filter({
      has: page.getByRole('button', { name: '清理索引' }),
    })
    page.once('dialog', (dialog) => dialog.accept())
    await cleanupRow.getByRole('button', { name: '清理索引' }).click()
    await expect(page.getByText('清理任务已提交')).toBeVisible()
    await expect(cleanupRow).toHaveCount(0, { timeout: 20_000 })

    await page.getByRole('link', { name: 'RAG 评测' }).click()
    await page.getByRole('combobox', { name: '当前知识库' }).last().selectOption({
      label: uniqueName,
    })
    await page.getByRole('button', { name: '新建运行' }).click()
    await page.getByPlaceholder('例如：检索回归 2026-07').fill(retrievalRunName)
    await page.getByLabel('上传 JSONL（可选，优先于已有选择）').setInputFiles({
      name: 'real-evaluation.jsonl',
      mimeType: 'application/x-ndjson',
      buffer: Buffer.from(
        '{"question":"persistence evidence","expected_answer":["evidence"],"source_ids":[],"tags":["real"]}',
      ),
    })
    await page.getByLabel('新数据集名称').fill(datasetName)
    await page.getByRole('button', { name: '提交运行' }).click()
    const retrievalRun = page.locator('tr').filter({ hasText: retrievalRunName })
    await expect(retrievalRun.getByLabel('状态：成功')).toBeVisible({
      timeout: 20_000,
    })
    await expect(page.getByText('hit_at_k').first()).toBeVisible()

    await page.getByRole('button', { name: '新建运行' }).click()
    await page.getByPlaceholder('例如：检索回归 2026-07').fill(ragRunName)
    await page.getByLabel('模式').selectOption('rag')
    await page.getByRole('button', { name: '提交运行' }).click()
    const ragRun = page.locator('tr').filter({ hasText: ragRunName })
    await expect(ragRun.getByLabel('状态：成功')).toBeVisible({
      timeout: 20_000,
    })
    await expect(page.getByText('隔离环境中的确定性回答 [S1]')).toBeVisible()

    await page.goto('/dashboard')
    await expect(page.getByRole('heading', { name: '系统总览' })).toBeVisible()
    await expect(page.locator('.metric-card')).toHaveCount(6)
    await expect(
      page
        .locator('a.compact-row')
        .filter({ hasText: 'real-api-document.txt' })
        .filter({ hasText: uniqueName }),
    ).toBeVisible()
    await expect(
      page
        .locator('a.compact-row')
        .filter({ hasText: `索引 · ${uniqueName}` })
        .first(),
    ).toBeVisible()
    await expect(
      page.locator('a.compact-row').filter({ hasText: `评测 · ${uniqueName}` }),
    ).toHaveCount(2)
    await expect(page.getByText('部分数据暂时不可用')).toHaveCount(0)
    await page
      .locator('a.compact-row')
      .filter({ hasText: 'real-api-document.txt' })
      .filter({ hasText: uniqueName })
      .click()
    await expect(page).toHaveURL(/\/files\?knowledgeBaseId=/u)

    await page.getByRole('link', { name: '知识库' }).click()
    card = page.locator('article.kb-card').filter({ hasText: uniqueName })
    await card.getByRole('button', { name: '删除知识库' }).click()
    await page.getByRole('button', { name: '确认删除' }).click()
    await expect(page.getByText('知识库包含文件或会话，不能删除')).toBeVisible()
    await page.getByRole('button', { name: '取消' }).click()

    await card.getByRole('button', { name: '打开' }).click()
    row = page.locator('tr').filter({ hasText: 'real-api-document.txt' })
    await row.getByRole('button', { name: '删除文件' }).click()
    await page.getByRole('button', { name: '确认删除' }).click()
    await expect(row).toHaveCount(0)
    await page.getByRole('link', { name: '知识库' }).click()
    card = page.locator('article.kb-card').filter({ hasText: uniqueName })
    await card.getByRole('button', { name: '删除知识库' }).click()
    await page.getByRole('button', { name: '确认删除' }).click()
    await expect(card).toHaveCount(0)
    await page.reload()
    await expect(
      page.locator('article.kb-card').filter({ hasText: uniqueName }),
    ).toHaveCount(0)

    expect(network).toEqual(
      expect.arrayContaining([
        'GET /api/knowledge-bases 200',
        'POST /api/knowledge-bases 201',
        'POST /api/files/upload 201',
        'POST /api/files/' + fileIdFrom(network) + '/process 202',
        'POST /api/chat/stream 200',
        'GET /api/dashboard 200',
      ]),
    )
    expect(
      network.some((item) =>
        /^POST \/api\/chat\/messages\/[^/]+\/retry\/stream 200$/u.test(item),
      ),
    ).toBe(true)
    expect(
      network.some((item) =>
        /^POST \/api\/chat\/messages\/[^/]+\/cancel 200$/u.test(item),
      ),
    ).toBe(true)
    expect(
      network.some((item) =>
        /^PUT \/api\/sessions\/[^/]+\/messages\/[^/]+\/feedback 200$/u.test(item),
      ),
    ).toBe(true)
    expect(
      network.some((item) => /^DELETE \/api\/knowledge-bases\/[^/]+ 409$/u.test(item)),
    ).toBe(true)
    expect(
      consoleErrors.filter(
        (message) =>
          !message.includes(
            'Failed to load resource: the server responded with a status of 409',
          ),
      ),
    ).toEqual([])
  })

  test('shows a real service-unreachable error without Mock fallback', async ({
    page,
  }) => {
    test.skip(!expectBackendDown, 'backend-down pass is separate')
    await page.goto('/knowledge-bases')
    await expect(
      page.getByText('后端服务不可达，请检查 FastAPI 是否已启动。'),
    ).toBeVisible()
    await expect(page.getByText('产品知识中台')).toHaveCount(0)
  })
})

function fileIdFrom(network: string[]): string {
  const request = network.find((item) =>
    /^POST \/api\/files\/[^/]+\/process 202$/u.test(item),
  )
  return request?.split('/')[3] ?? '<missing>'
}
