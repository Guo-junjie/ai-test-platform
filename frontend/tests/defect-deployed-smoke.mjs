/** 已部署页面只读验收；会话从私有临时文件读取，绝不在日志中输出。 */
import { createRequire } from 'node:module'
import assert from 'node:assert/strict'
import { readFile, mkdir } from 'node:fs/promises'
const require = createRequire(import.meta.url)
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright')
assert.ok(process.env.SESSION_FILE, 'SESSION_FILE is required')
const session = JSON.parse(await readFile(process.env.SESSION_FILE, 'utf8'))
const origin = process.env.FRONTEND_URL || 'http://192.168.125.128:3000'
const browser = await chromium.launch({ headless: true, ...(process.env.BROWSER_PATH ? { executablePath: process.env.BROWSER_PATH } : {}) })
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
await context.addInitScript(({ token, user }) => { localStorage.setItem('token', token); localStorage.setItem('user', JSON.stringify(user)) }, session)
const page = await context.newPage(), errors = [], failedApi = [], writes = []
page.on('pageerror', error => errors.push(error.message))
page.on('response', response => { if (response.url().includes('/api/') && response.status() >= 400) failedApi.push({ status: response.status(), path: new URL(response.url()).pathname }) })
page.on('request', request => { if (request.url().includes('/api/') && !['GET', 'HEAD', 'OPTIONS'].includes(request.method())) writes.push(new URL(request.url()).pathname) })
try {
  const response = await context.request.get(`${origin}/api/projects`, { headers: { Authorization: `Bearer ${session.token}` } })
  assert.equal(response.status(), 200)
  const project = (await response.json()).data.list[0]
  await page.goto(`${origin}/defects${project ? `?project_id=${project.id}` : ''}`)
  await page.getByRole('button', { name: '登记缺陷', exact: true }).waitFor()
  await page.getByRole('button', { name: '登记缺陷', exact: true }).click()
  const form = page.locator('.defect-form-drawer'); await form.waitFor()
  if (project) await form.getByRole('button', { name: '保存缺陷', exact: true }).waitFor({ state: 'visible' })
  for (const name of ['缺陷标题', '缺陷描述', '复现步骤 1', '预期结果', '实际结果']) await form.getByRole('textbox', { name, exact: true }).waitFor()
  await form.getByRole('textbox', { name: '缺陷标题', exact: true }).fill('浏览器只读验收：此输入不会保存')
  await form.getByRole('textbox', { name: '缺陷描述', exact: true }).fill('检查真实部署的登记表单、目录、人员和未保存保护。')
  await form.getByRole('textbox', { name: '复现步骤 1', exact: true }).fill('打开产品并提交订单')
  await form.getByRole('textbox', { name: '预期结果', exact: true }).fill('订单金额符合规则')
  await form.getByRole('button', { name: '添加步骤', exact: true }).click()
  await form.getByRole('textbox', { name: '复现步骤 2', exact: true }).fill('核对金额与优惠结果')
  await mkdir('test-results', { recursive: true })
  await page.screenshot({ path: 'test-results/defects-deployed-desktop.png', fullPage: true })
  await page.setViewportSize({ width: 390, height: 844 })
  await page.waitForFunction(() => { const box = document.querySelector('.defect-form-drawer')?.getBoundingClientRect(); return box && box.left >= -1 && box.right <= innerWidth + 1 })
  assert.equal(await form.evaluate(element => element.scrollWidth > element.clientWidth + 2), false)
  assert.equal(await form.evaluate(element => { const box = element.getBoundingClientRect(); const target = document.elementFromPoint(box.left + 24, 100); return !!target && element.contains(target) }), true, '移动导航不能遮挡登记抽屉')
  await page.screenshot({ path: 'test-results/defects-deployed-mobile.png', fullPage: true })
  await form.getByRole('button', { name: '取消', exact: true }).click()
  await page.getByRole('button', { name: '继续编辑', exact: true }).click(); assert.equal(await form.isVisible(), true)
  await form.getByRole('button', { name: '取消', exact: true }).click()
  await page.getByRole('button', { name: '放弃并离开', exact: true }).click(); await form.waitFor({ state: 'hidden' })
  assert.deepEqual(errors, []); assert.deepEqual(failedApi, []); assert.deepEqual(writes, [])
  console.log('PASS：真实部署页面、项目选项、结构化字段、步骤编辑、未保存保护及移动布局；没有写入业务数据。')
} finally { await browser.close() }
