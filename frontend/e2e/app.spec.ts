import { expect, test, type Page } from '@playwright/test'

let runtimeProblems: string[] = []

function monitorRuntime(page: Page): void {
  runtimeProblems = []
  page.on('pageerror', (error) => runtimeProblems.push(`pageerror: ${error.message}`))
  page.on('console', (message) => {
    const text = message.text()
    if (message.type() === 'error' || text.includes('[Vue warn]')) {
      runtimeProblems.push(`console:${message.type()}: ${text}`)
    }
  })
  page.on('requestfailed', (request) => {
    runtimeProblems.push(
      `requestfailed: ${request.method()} ${request.url()} ${request.failure()?.errorText ?? ''}`,
    )
  })
  page.on('response', (response) => {
    if (response.status() >= 400) {
      runtimeProblems.push(`response:${response.status()}: ${response.url()}`)
    }
  })
  page.on('request', (request) => {
    const url = request.url()
    if (url.startsWith('http://') && !url.startsWith('http://127.0.0.1:4173')) {
      runtimeProblems.push(`external request: ${url}`)
    }
  })
}

async function expectNoRootOverflow(page: Page): Promise<void> {
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  )
  expect(overflow).toBeLessThanOrEqual(1)
}

test.beforeEach(async ({ context, page }) => {
  await context.grantPermissions(['clipboard-read', 'clipboard-write'])
  monitorRuntime(page)
})

test.afterEach(async ({ page }) => {
  if (page.url().startsWith('http://127.0.0.1:4173')) {
    await expectNoRootOverflow(page)
  }
  expect(runtimeProblems).toEqual([])
})

test('root redirect, nine business routes and 404 are reachable', async ({ page }) => {
  await page.goto('/')
  await expect(page).toHaveURL(/\/dashboard$/u)

  const routes = [
    ['/dashboard', '系统总览'],
    ['/chat', '智能问答'],
    ['/knowledge-bases', '知识库'],
    ['/files', '文件管理'],
    ['/sessions', '会话历史'],
    ['/retrieval', '检索测试'],
    ['/indexes', '索引管理'],
    ['/evaluation', 'RAG 评测'],
    ['/settings', '系统设置'],
  ] as const

  for (const [path, title] of routes) {
    await page.goto(path)
    await expect(page.getByRole('heading', { name: title, level: 1 })).toBeVisible()
    await expectNoRootOverflow(page)
  }

  await page.goto('/this-route-does-not-exist')
  await expect(
    page.getByRole('heading', { name: '页面不存在', level: 1 }),
  ).toBeVisible()
  await page.getByRole('link', { name: '返回系统总览' }).click()
  await expect(page).toHaveURL(/\/dashboard$/u)
})

test('chart runtime stays deferred until Dashboard needs it', async ({ page }) => {
  const chartAssetRequests: string[] = []
  page.on('request', (request) => {
    const url = request.url()
    if (/\/assets\/(?:echarts|zrender)-[^/]+\.js$/u.test(url)) {
      chartAssetRequests.push(url)
    }
  })

  await page.goto('/chat')
  await expect(page.getByRole('heading', { name: '智能问答', level: 1 })).toBeVisible()
  expect(chartAssetRequests).toEqual([])

  await page.goto('/dashboard')
  await expect(
    page.getByRole('img', { name: '最近七天真实活动趋势折线图' }),
  ).toBeVisible()
  await expect(page.getByRole('img', { name: '文件处理状态环形图' })).toBeVisible()
  await expect.poll(() => chartAssetRequests.length).toBe(2)
})

test('sidebar, keyboard focus and 1024px chat sheets remain usable', async ({
  page,
}) => {
  await page.goto('/dashboard')
  const shell = page.locator('.app-shell')
  await page.getByRole('button', { name: '折叠侧边栏' }).click()
  await expect(shell).toHaveClass(/is-collapsed/u)
  await page.getByRole('link', { name: '智能问答' }).focus()
  await expect(page.getByRole('link', { name: '智能问答' })).toBeFocused()

  await page.setViewportSize({ width: 1024, height: 768 })
  await page.goto('/chat')
  await expect(page.locator('.chat-side-left')).toBeHidden()
  await expect(page.locator('.chat-side-right')).toBeHidden()
  await page.getByRole('button', { name: '打开会话列表' }).click()
  await expect(page.getByRole('dialog')).toContainText('会话列表')
  await page.getByRole('button', { name: '关闭侧边面板' }).click()
  await page.getByRole('button', { name: '打开引用来源' }).click()
  await expect(page.getByRole('dialog')).toContainText('引用来源')
})

test('knowledge base CRUD and file processing workflows update Mock state', async ({
  page,
}) => {
  await page.goto('/knowledge-bases')
  await expect(page.getByRole('heading', { name: '知识库', level: 1 })).toBeVisible()

  await page.getByRole('button', { name: '新建知识库' }).first().click()
  await page.locator('#kb-name').fill('发布资料中心')
  await page.locator('#kb-description').fill('版本发布流程与交付材料')
  await page.getByRole('button', { name: '创建知识库' }).click()

  let card = page.locator('article.kb-card').filter({ hasText: '发布资料中心' })
  await expect(card).toBeVisible()
  await card.getByRole('button', { name: '编辑知识库' }).click()
  await page.locator('#kb-name').fill('发布资料中心 2')
  await page.getByRole('button', { name: '保存修改' }).click()
  card = page.locator('article.kb-card').filter({ hasText: '发布资料中心 2' })
  await expect(card).toBeVisible()

  await card.getByRole('button', { name: '打开' }).click()
  await expect(page).toHaveURL(/\/files\?knowledgeBaseId=/u)
  await page.getByRole('button', { name: '上传文件' }).first().click()
  await page.locator('input[type="file"]').setInputFiles({
    name: '发布流程补充说明.txt',
    mimeType: 'text/plain',
    buffer: Buffer.from('# 发布流程\n\nMock metadata only.'),
  })
  await page.getByRole('button', { name: '加入处理队列' }).click()

  const row = page.locator('tr').filter({ hasText: '发布流程补充说明.txt' })
  await expect(row).toContainText('等待中')
  await row.getByRole('button', { name: '处理文件' }).click()
  await expect(row.getByLabel('状态：成功')).toBeVisible({ timeout: 8_000 })
  await row.getByRole('button', { name: '查看文件详情' }).click()
  await expect(page.getByRole('dialog')).toContainText('发布流程补充说明.txt')
  await page.getByRole('switch', { name: '显示文件技术详情' }).click()
  await expect(page.getByRole('dialog')).toContainText('content_hash')
  await page.getByRole('button', { name: '关闭侧边面板' }).click()
  await row.getByRole('button', { name: '删除文件' }).click()
  await page.getByRole('button', { name: '确认删除' }).click()
  await expect(row).toHaveCount(0)

  await page.getByRole('link', { name: '知识库' }).click()
  await expect(page).toHaveURL(/\/knowledge-bases$/u)
  card = page.locator('article.kb-card').filter({ hasText: '发布资料中心 2' })
  await card.getByRole('button', { name: '删除知识库' }).click()
  await page.getByRole('button', { name: '确认删除' }).click()
  await expect(card).toHaveCount(0)

  await page.goto('/files')
  const failedRow = page.locator('tr').filter({ hasText: '损坏的技术文档.pdf' })
  await expect(failedRow.getByLabel('状态：失败')).toBeVisible()
  await failedRow.getByRole('button', { name: '查看文件详情' }).click()
  await expect(page.getByRole('dialog')).toContainText(
    'PDF parsing failed: invalid xref table',
  )
  await page.getByRole('button', { name: '关闭侧边面板' }).click()
  await failedRow.getByRole('button', { name: '重试处理文件' }).click()
  await expect(failedRow.getByLabel('状态：失败')).toBeVisible({ timeout: 8_000 })
})

test('sessions and chat cover create, search, stream, stop, sources and feedback', async ({
  page,
}) => {
  await page.goto('/sessions')
  await expect(page.getByText('混合检索的配置方式').first()).toBeVisible()
  const search = page.getByPlaceholder('搜索会话')
  await search.fill('Embedding 模型升级')
  await expect(page.getByText('Embedding 模型升级').first()).toBeVisible()
  await page.getByText('Embedding 模型升级').first().click()
  await page.getByRole('button', { name: '删除当前会话' }).click()
  await page.getByRole('button', { name: '确认删除' }).click()
  await expect(page.getByText('会话删除失败。')).toBeVisible()

  await page.goto('/chat')
  const composer = page.getByLabel('输入问题')
  await composer.fill('请给出产品文档的混合检索配置')
  await page.getByRole('button', { name: '发送问题' }).click()
  await expect(page.locator('.chat-side-right .source-card')).toHaveCount(5, {
    timeout: 10_000,
  })

  const latestAssistant = page.locator('.message:not(.message-user)').last()
  await latestAssistant.getByRole('button', { name: '复制回答' }).click()
  await expect(page.getByText('回答已复制')).toBeVisible()
  const like = latestAssistant.getByRole('button', { name: '点赞回答' })
  const dislike = latestAssistant.getByRole('button', { name: '点踩回答' })
  await like.click()
  await expect(like).toHaveClass(/button-default/u)
  await dislike.click()
  await expect(dislike).toHaveClass(/button-default/u)
  await expect(like).toHaveClass(/button-ghost/u)

  await page.locator('.chat-side-right .source-card').first().click()
  await expect(page.getByRole('dialog')).toContainText('来源详情')
  await page.getByRole('button', { name: '关闭侧边面板' }).click()

  await composer.fill('请生成一个可以停止的回答')
  await page.getByRole('button', { name: '发送问题' }).click()
  const stopButton = page.getByRole('button', { name: '停止生成' })
  await expect(stopButton).toBeVisible()
  await stopButton.click()
  await expect(page.getByText('已停止生成')).toBeVisible()

  await composer.fill('无来源')
  await page.getByRole('button', { name: '发送问题' }).click()
  await expect(page.getByText(/没有检索到达到阈值/u).last()).toBeVisible({
    timeout: 10_000,
  })
  await expect(page.locator('.chat-side-right .source-card')).toHaveCount(0)

  await composer.fill('触发失败')
  await page.getByRole('button', { name: '发送问题' }).click()
  await expect(page.getByText('模型请求失败').last()).toBeVisible({
    timeout: 8_000,
  })
  await expect(
    page.locator('.message:not(.message-user)').last().getByRole('button', {
      name: '重试回答',
    }),
  ).toBeVisible()
})

test('retrieval, indexes, evaluation and settings complete their core flows', async ({
  page,
}) => {
  await page.goto('/retrieval')
  const query = page.getByLabel('查询文本')
  await query.fill('混合检索配置')
  await page.getByRole('button', { name: '执行检索' }).first().click()
  await expect(page.locator('.retrieval-result')).toHaveCount(4)
  await page.getByRole('button', { name: 'JSON' }).click()
  await expect(page.locator('.json-view')).toContainText('"queryTimeMs"')
  await page.getByRole('button', { name: '结果卡片' }).click()
  await query.fill('无结果')
  await page.getByRole('button', { name: '执行检索' }).first().click()
  await expect(page.getByText('没有匹配结果')).toBeVisible()
  await query.fill('失败')
  await page.getByRole('button', { name: '执行检索' }).first().click()
  await expect(page.getByText('检索请求失败。')).toBeVisible()

  await page.goto('/indexes')
  const activeRow = page.locator('tr').filter({ hasText: 'kb_product_active_g12' })
  await expect(activeRow).toBeVisible()
  await page.getByRole('button', { name: '重建索引' }).click()
  await expect(page.getByText('索引重建已提交')).toBeVisible()
  const previousBeforeRollback = page.locator('tr').filter({
    has: page.getByRole('button', { name: '回滚索引' }),
  })
  page.once('dialog', (dialog) => dialog.accept())
  await previousBeforeRollback.getByRole('button', { name: '回滚索引' }).click()
  await expect(page.getByText('已回滚到上一版本索引')).toBeVisible()
  const previousRow = page.locator('tr').filter({
    has: page.getByRole('button', { name: '清理索引' }),
  })
  page.once('dialog', (dialog) => dialog.accept())
  await previousRow.getByRole('button', { name: '清理索引' }).click()
  await expect(previousRow).toHaveCount(0)

  await page.goto('/evaluation')
  await page.getByRole('button', { name: '新建运行' }).click()
  await page.getByPlaceholder('例如：检索回归 2026-07').fill('发布质量回归')
  await page.getByLabel('上传 JSONL（可选，优先于已有选择）').setInputFiles({
    name: 'quality.jsonl',
    mimeType: 'application/x-ndjson',
    buffer: Buffer.from(
      '{"question":"如何发布？","expected_answer":["发布"],"source_ids":[],"tags":[]}',
    ),
  })
  await page.getByLabel('新数据集名称').fill('发布质量数据集')
  await page.getByRole('button', { name: '提交运行' }).click()
  const taskRow = page.locator('tr').filter({ hasText: '发布质量回归' })
  await expect(taskRow.getByLabel('状态：成功')).toBeVisible({
    timeout: 10_000,
  })
  await expect(page.getByText('服务器持久化')).toBeVisible()

  await page.goto('/settings')
  const topK = page.getByLabel('默认 TopK')
  await topK.fill('0')
  await page.getByRole('button', { name: '保存设置' }).click()
  await expect(page.getByText('默认 TopK 必须是 1–100 的整数。')).toBeVisible()
  await topK.fill('7')
  await page.getByRole('button', { name: '保存设置' }).click()
  await expect(page.getByText('服务器设置已保存并重新读取')).toBeVisible()
  await expect(page.getByText('尚未保存')).toHaveCount(0)
  await topK.fill('8')
  await page.getByRole('button', { name: '撤销未保存修改' }).click()
  await expect(topK).toHaveValue('7')
  await expect(page.getByText('前端模式').locator('..')).toContainText('Mock')
  await expect(page.getByText('Mock Mode')).toHaveCount(0)
})

test('all business pages have no root overflow at 1024px', async ({ page }) => {
  await page.setViewportSize({ width: 1024, height: 768 })
  for (const path of [
    '/dashboard',
    '/chat',
    '/knowledge-bases',
    '/files',
    '/sessions',
    '/retrieval',
    '/indexes',
    '/evaluation',
    '/settings',
  ]) {
    await page.goto(path)
    await expect(page.locator('main')).toBeVisible()
    await expectNoRootOverflow(page)
  }
})
