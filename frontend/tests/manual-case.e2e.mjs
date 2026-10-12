/** 人工录入浏览器回归；请求在浏览器中模拟，不写入部署环境的业务数据。 */
import { createRequire } from 'node:module'
import assert from 'node:assert/strict'
import { mkdir } from 'node:fs/promises'

const require = createRequire(import.meta.url)
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright')
const browser = await chromium.launch({ headless: true, ...(process.env.BROWSER_PATH ? { executablePath: process.env.BROWSER_PATH } : {}) })
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
const page = await context.newPage()
const errors = []
page.on('pageerror', error => errors.push(error.message))
let assets = []
let creates = []
let sequence = 0
const projectId = '11111111-1111-4111-8111-111111111111'
const docId = '22222222-2222-4222-8222-222222222222'
const project = { id: projectId, name: '订单产品', source_type: 'upload', project_kind: 'api_testing', capabilities: ['test_cases'], source_config: {}, created_at: new Date().toISOString() }
await context.addInitScript(() => {
  localStorage.setItem('token', 'manual-case-browser-test')
  localStorage.setItem('user', JSON.stringify({ id: 'tester', username: 'test-engineer', role: 'tester', is_active: true }))
})
await page.route('**/api/**', async route => {
  const request = route.request()
  const url = new URL(request.url())
  if (!url.pathname.startsWith('/api/')) return route.continue()
  let data = { items: [], total: 0, list: [] }
  let status = 200
  if (url.pathname === '/api/projects') data = { list: [project], items: [project], total: 1 }
  else if (url.pathname === `/api/projects/${projectId}`) data = project
  else if (url.pathname === '/api/cases/manual/options') data = { folders: ['订单'], tags: ['冒烟'], requirements: [{ id: docId, filename: '订单需求.md' }] }
  else if (url.pathname === '/api/cases' && request.method() === 'POST') {
    const payload = request.postDataJSON()
    creates.push(payload)
    const duplicate = assets.find(item => item.title.toLowerCase() === payload.title.toLowerCase())
    if (duplicate && !payload.allow_duplicate) {
      return route.fulfill({ status: 409, json: { detail: { code: 'CASE_DUPLICATE', message: '发现同名用例', duplicates: [{ id: duplicate.id, title: duplicate.title, folder: duplicate.folder }] } } })
    }
    data = { ...payload, id: `case-${++sequence}`, source: 'manual', execution_kind: 'manual', status: 'draft', review_state: 'draft', version: 1, request_data: { steps: payload.steps, preconditions: payload.preconditions, requirement_doc_id: payload.requirement_doc_id, requirement_ref: payload.requirement_ref }, expected_result: { text: payload.expected_result }, created_at: new Date().toISOString() }
    assets.unshift(data)
  } else if (url.pathname === '/api/cases') data = { items: assets, total: assets.length }
  else if (/\/api\/cases\/case-\d+\/versions/.test(url.pathname)) data = [{ version: 1, change_type: 'created', snapshot: assets[0] }]
  else if (/\/api\/cases\/case-\d+\/traceability/.test(url.pathname)) data = { source: { source: 'manual', requirement: { filename: '订单需求.md' } }, plans: [], plan_revisions: [], recent_runs: [], defects: [] }
  else if (/\/api\/cases\/case-\d+$/.test(url.pathname)) data = assets.find(item => item.id === url.pathname.split('/').pop())
  else if (url.pathname === '/api/auth/me') data = { id: 'tester', username: 'test-engineer', role: 'tester', is_active: true }
  else if (url.pathname === '/api/health') data = { status: 'healthy', env: 'test' }
  await route.fulfill({ status, json: { code: 0, data, message: 'ok' } })
})
const drawer = page.locator('.manual-case-drawer')
const title = () => drawer.getByPlaceholder('例如：未登录用户无法提交订单')
const expected = () => drawer.getByPlaceholder('填写可验证的结果，例如：跳转登录页，订单未被创建')
const firstStep = () => drawer.getByRole('textbox', { name: '步骤 1 操作内容' })
let checks = 0
function passed(label) { checks++; console.log(`PASS ${label}`) }

try {
  await page.goto(`${process.env.FRONTEND_URL || 'http://127.0.0.1:3100'}/case-library?project_id=${projectId}`)
  await page.getByRole('button', { name: '手动添加用例', exact: true }).nth(1).waitFor()
  passed('空列表显示引导入口')
  await page.getByRole('button', { name: '手动添加用例', exact: true }).first().click()
  await drawer.getByRole('button', { name: '保存用例', exact: true }).click()
  await drawer.getByText('请填写内容，不能只输入空格').first().waitFor()
  assert.equal(creates.length, 0)
  passed('必填校验阻止空表单提交')
  await title().fill('临时订单场景')
  await drawer.getByRole('button', { name: '取消', exact: true }).click()
  await page.getByRole('button', { name: '继续编辑', exact: true }).last().click()
  assert.equal(await title().inputValue(), '临时订单场景')
  passed('关闭拦截取消后保留输入')
  // 验证真实 Vue Router 菜单导航，同样保留未保存输入。
  // 抽屉遮罩阻止鼠标点击菜单，触发菜单事件来覆盖 Router 编程导航的离开保护。
  await page.getByRole('menuitem', { name: '项目', exact: true }).dispatchEvent('click')
  await page.getByRole('button', { name: '继续编辑', exact: true }).last().click()
  assert.match(page.url(), /case-library/)
  passed('页面导航拦截')
  let refreshBlocked = false
  page.once('dialog', async dialog => { refreshBlocked = dialog.type() === 'beforeunload'; await dialog.dismiss() })
  await page.reload({ waitUntil: 'domcontentloaded' }).catch(() => {})
  assert.equal(refreshBlocked, true)
  assert.equal(await title().inputValue(), '临时订单场景')
  passed('刷新拦截保留未保存内容')
  await firstStep().fill('打开购物车')
  await drawer.getByRole('button', { name: '添加步骤', exact: true }).click()
  await drawer.getByRole('textbox', { name: '步骤 2 操作内容' }).fill('提交订单')
  await drawer.getByRole('button', { name: '上移步骤 2', exact: true }).click()
  assert.equal(await firstStep().inputValue(), '提交订单')
  await drawer.getByRole('button', { name: '添加步骤', exact: true }).click()
  await drawer.getByRole('button', { name: '删除步骤 3', exact: true }).click()
  passed('步骤动态增删和顺序调整')
  await drawer.getByPlaceholder('例如：测试账号已注册、购物车中有商品（选填）').fill('用户已登录\n购物车有商品')
  await expected().fill('返回订单编号')
  // 通过表单项定位 Element Plus 选择器，兼容其动态 aria 名称。
  await drawer.locator('.el-form-item').filter({ has: page.getByText('所属模块 / 目录', { exact: true }) }).getByRole('combobox').click()
  await page.getByRole('option', { name: '订单', exact: true }).click()
  await drawer.locator('.el-form-item').filter({ has: page.getByText('关联需求文档', { exact: true }) }).getByRole('combobox').click()
  await page.getByRole('option', { name: '订单需求.md', exact: true }).click()
  await drawer.getByPlaceholder('例如：REQ-102 或需求链接（选填）').fill('REQ-102')
  await drawer.getByRole('button', { name: '保存并继续添加', exact: true }).click()
  await page.getByText('用例已保存，目录和标签已保留，可继续添加下一条', { exact: true }).waitFor()
  assert.equal(creates[0].folder, '订单')
  assert.deepEqual(creates[0].steps, ['提交订单', '打开购物车'])
  assert.equal(creates[0].requirement_doc_id, docId)
  assert.equal(await title().inputValue(), '')
  assert.equal(await firstStep().inputValue(), '')
  assert.equal(await drawer.getByPlaceholder('例如：REQ-102 或需求链接（选填）').inputValue(), 'REQ-102')
  await page.locator('.new-case-row').first().waitFor()
  passed('连续保存清空内容、保留上下文并高亮新增行')
  await title().fill('临时订单场景'); await firstStep().fill('再次验证'); await expected().fill('验证成功')
  await drawer.getByRole('button', { name: '保存用例', exact: true }).click()
  await drawer.getByText('当前项目已有同名用例，请核对内容后再保存').waitFor()
  assert.equal(assets.length, 1)
  passed('重复标题提醒阻止意外录入')
  await drawer.getByRole('button', { name: '保存用例', exact: true }).click()
  await page.getByRole('button', { name: '返回修改', exact: true }).click()
  assert.equal(assets.length, 1)
  await drawer.getByRole('button', { name: '保存用例', exact: true }).click()
  await page.getByRole('button', { name: '仍然添加', exact: true }).click()
  await drawer.waitFor({ state: 'hidden' })
  assert.equal(assets.length, 2)
  assert.equal(creates.at(-1).allow_duplicate, true)
  passed('重复确认支持返回修改或明确继续添加')
  await page.locator('.new-case-row').getByRole('button', { name: '查看', exact: true }).click()
  await page.getByRole('tab', { name: '请求与断言', exact: true }).click()
  await page.getByText('再次验证', { exact: true }).waitFor()
  passed('保存后详情展示手工步骤和预期结果')
  await page.getByRole('button', { name: '关闭', exact: true }).last().click()
  await page.getByRole('button', { name: '手动添加用例', exact: true }).first().click()
  await title().fill('未保存内容')
  await drawer.getByRole('button', { name: '取消', exact: true }).click()
  await page.getByRole('button', { name: '放弃并离开', exact: true }).click()
  await drawer.waitFor({ state: 'hidden' })
  passed('明确放弃后关闭表单')
  await page.setViewportSize({ width: 390, height: 844 })
  await page.getByRole('button', { name: '手动添加用例', exact: true }).first().click()
  await drawer.waitFor()
  await page.waitForFunction(() => {
    const box = document.querySelector('.manual-case-drawer')?.getBoundingClientRect()
    return box && box.left >= 0 && Math.abs(box.right - window.innerWidth) < 2
  })
  const overflow = await drawer.evaluate(element => element.scrollWidth > element.clientWidth + 2)
  assert.equal(overflow, false)
  await mkdir('test-results', { recursive: true })
  await page.screenshot({ path: 'test-results/manual-case-mobile.png', fullPage: true })
  passed('移动端抽屉无横向溢出')
  await page.setViewportSize({ width: 1440, height: 1000 })
  await title().fill('未登录用户无法提交订单')
  await firstStep().fill('在购物车页面点击「提交订单」')
  await expected().fill('跳转至登录页，订单未被创建')
  await page.screenshot({ path: 'test-results/manual-case-desktop.png', fullPage: true })
  await drawer.getByRole('button', { name: '取消', exact: true }).click()
  await page.getByRole('button', { name: '放弃并离开', exact: true }).last().click()
  await drawer.waitFor({ state: 'hidden' })
  await page.goto(`${process.env.FRONTEND_URL || 'http://127.0.0.1:3100'}/projects/${projectId}/cases`)
  await page.getByRole('button', { name: '手动添加用例', exact: true }).first().click()
  await drawer.waitFor()
  assert.match(page.url(), /create=manual/)
  passed('项目工作区入口带入项目并自动打开录入表单')
  await drawer.getByRole('button', { name: '取消', exact: true }).click()
  await drawer.waitFor({ state: 'hidden' })
  await page.goto(`${process.env.FRONTEND_URL || 'http://127.0.0.1:3100'}/projects/${projectId}/cases`)
  await page.getByRole('button', { name: '详情', exact: true }).first().click()
  await page.locator('.case-drawer').waitFor()
  await page.getByRole('tab', { name: '请求与断言', exact: true }).click()
  await page.getByText('再次验证', { exact: true }).waitFor()
  passed('项目用例详情链接直接展示新用例')
  assert.deepEqual(errors, [])
  console.log(`${checks} browser checks passed; no page errors`)
} catch (error) {
  console.error('URL:', page.url(), 'PAGE ERRORS:', errors)
  console.error((await page.locator('body').innerText()).slice(0, 5000))
  await mkdir('test-results', { recursive: true })
  await page.screenshot({ path: 'test-results/manual-case-failure.png', fullPage: true })
  throw error
} finally { await browser.close() }
