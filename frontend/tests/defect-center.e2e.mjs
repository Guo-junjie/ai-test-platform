/** 缺陷工作台浏览器回归：模拟 HTTP，不写部署环境业务库；领域流转另有真实 PG 验收。 */
import { createRequire } from 'node:module'
import assert from 'node:assert/strict'
import { mkdir } from 'node:fs/promises'
const require = createRequire(import.meta.url)
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright')
const browser = await chromium.launch({ headless: true, ...(process.env.BROWSER_PATH ? { executablePath: process.env.BROWSER_PATH } : {}) })
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
const page = await context.newPage(), errors = [], writes = []
page.on('pageerror', error => errors.push(error.message))
const pid = '11111111-1111-4111-8111-111111111111', uid = '22222222-2222-4222-8222-222222222222', qa = '33333333-3333-4333-8333-333333333333'
const project = { id: pid, name: '订单产品', source_type: 'upload', project_kind: 'api_testing', capabilities: ['test_cases'] }
const people = [{ id: uid, username: '开发工程师', roles: ['developer', 'project_manager'] }, { id: qa, username: '验证工程师', roles: ['qa'] }]
const states = { new: '新建', unassigned: '待分配', in_progress: '处理中', pending_verification: '待验证', resolved: '已解决', closed: '已关闭', reopened: '重开', rejected: '已拒绝' }
const flow = { new: ['triage', '完成分诊', 'unassigned'], unassigned: ['start', '开始处理', 'in_progress'], in_progress: ['submit_fix', '提交修复', 'pending_verification'], pending_verification: ['verify_pass', '验证通过', 'resolved'], resolved: ['close', '关闭缺陷', 'closed'], closed: ['reopen', '重开缺陷', 'reopened'], reopened: ['resume', '继续处理', 'in_progress'] }
const metadata = { can_create: true, can_configure: true, roles: ['project_manager'], modules: [{ id: 'module1', path: '订单', name: '订单' }], iterations: [], releases: [], environments: [], requirements: [], cases: [] }
let defects = [], serial = 0, history = [], failListing = false, conflictOnce = false
function detail(record) {
  const next = flow[record.workflow_state]
  return { ...record, workflow_state_label: states[record.workflow_state], permissions: { edit: true, assign: true, delete: true, restore: false }, transitions: next ? [{ action_id: next[0], label: next[1], to: next[2], allowed: true, required_fields: ['submit_fix', 'verify_pass', 'reopen'].includes(next[0]) ? ['note'] : [] }] : [], references: [], affected_releases: [], affected_release_ids: [], project_name: project.name, assignee_name: record.assignee_id ? '开发工程师' : null, verifier_name: record.verifier_id ? '验证工程师' : null }
}
await context.addInitScript(({ uid }) => {
  localStorage.setItem('token', 'defect-browser-test')
  localStorage.setItem('user', JSON.stringify({ id: uid, username: '项目负责人', role: 'test_manager', is_active: true }))
  // 模拟平台通过普通 HTTP/IP 访问时没有 randomUUID 的浏览器环境。
  Object.defineProperty(window.crypto, 'randomUUID', { value: undefined, configurable: true })
}, { uid })
await page.route('**/api/**', async route => {
  const request = route.request(), url = new URL(request.url()), path = url.pathname, method = request.method()
  if (!path.startsWith('/api/')) return route.continue()
  let data = { list: [], items: [], total: 0 }
  if (path === '/api/projects') data = { list: [project], total: 1 }
  else if (path === '/api/auth/me') data = { id: uid, username: '项目负责人', role: 'test_manager', is_active: true }
  else if (path === '/api/defects/metadata') data = metadata
  else if (path === '/api/defects/participants') data = { items: people }
  else if (path === '/api/defects/duplicates') data = { items: defects.filter(item => item.title === url.searchParams.get('title') && item.id !== url.searchParams.get('exclude_defect_id')).map(detail) }
  else if (path === '/api/defects' && method === 'POST') {
    const input = request.postDataJSON(); writes.push(input)
    const record = { ...input, id: `defect-${++serial}`, defect_key: `BUG-000000${serial}`, workflow_state: 'new', row_version: 1, source: 'manual', labels: input.labels || [], created_at: new Date().toISOString(), updated_at: new Date().toISOString(), severity_label: '一般', priority_label: '普通', defect_type_label: '业务缺陷', reopened_count: 0 }
    defects.unshift(record); data = detail(record)
  } else if (path === '/api/defects') {
    if (failListing) return route.fulfill({ status: 500, json: { detail: '模拟列表故障' } })
    const q = url.searchParams.get('q'), state = url.searchParams.get('workflow_states'), view = url.searchParams.get('view')
    const rows = defects.filter(item => (!q || item.title.includes(q)) && (!state || item.workflow_state === state) && (view !== 'triage' || ['new', 'unassigned'].includes(item.workflow_state)))
    data = { list: rows.map(detail), total: rows.length, stats: { backlog: rows.filter(item => !['resolved', 'closed'].includes(item.workflow_state)).length, by_severity: { P2: rows.length }, pending_verification: rows.filter(item => item.workflow_state === 'pending_verification').length } }
  } else if (/\/defects\/defect-\d+\/transitions$/.test(path) && method === 'POST') {
    const input = request.postDataJSON(), record = defects.find(item => item.id === path.split('/')[3]); writes.push(input)
    if (conflictOnce) { conflictOnce = false; record.row_version++; return route.fulfill({ status: 409, json: { detail: { error_code: 'DEFECT_VERSION_CONFLICT', message: '缺陷已被其他人更新，请刷新后重新提交', current_version: record.row_version } } }) }
    const previous = record.workflow_state; record.workflow_state = flow[previous][2]; record.row_version++
    Object.assign(record, input.fields); if (record.workflow_state === 'reopened') record.reopened_count++
    history.push({ id: String(history.length), sequence: history.length + 1, event_type: input.action_id, actor_name: '项目负责人', from_state: previous, to_state: record.workflow_state, note: input.note, occurred_at: new Date().toISOString(), changes: { assignee_id: { before: null, after: uid } }, display_changes: { assignee_id: { before: null, after: '开发工程师' } } })
    data = { detail: detail(record), row_version: record.row_version }
  } else if (/\/defects\/defect-\d+\/assign$/.test(path)) {
    const record = defects.find(item => item.id === path.split('/')[3]); Object.assign(record, request.postDataJSON()); record.row_version++; data = { detail: detail(record) }
  } else if (/\/defects\/defect-\d+\/events$/.test(path)) data = { items: history, has_more: false }
  else if (/\/defects\/defect-\d+\/occurrences$/.test(path)) data = { items: [] }
  else if (/\/defects\/defect-\d+$/.test(path)) {
    const record = defects.find(item => item.id === path.split('/')[3])
    if (method === 'PUT') {
      const input = request.postDataJSON(); writes.push(input)
      if (conflictOnce) { conflictOnce = false; record.row_version++; record.description = '其他成员已补充证据'; return route.fulfill({ status: 409, json: { detail: { message: '缺陷已被其他人更新，请刷新后重新提交' } } }) }
      assert.equal(input.expected_version, record.row_version)
      Object.assign(record, input); record.row_version++
    }
    data = detail(record)
  }
  await route.fulfill({ json: { code: 0, data, message: 'ok' } })
})
const form = page.locator('.defect-form-drawer'), drawer = page.locator('.defect-detail-drawer'), dialog = page.locator('.defect-action-dialog')
let checks = 0
const passed = text => { console.log(`PASS ${++checks}: ${text}`) }
async function select(container, name, option) {
  const input = container.getByRole('combobox', { name, exact: true })
  await input.click()
  const listId = await input.getAttribute('aria-controls')
  await page.locator(`[id="${listId}"]`).getByRole('option', { name: option, exact: true }).click()
}
async function action(label, note = '核对并执行本次操作') {
  await drawer.getByRole('button', { name: label, exact: true }).click(); await dialog.waitFor()
  await dialog.getByRole('textbox', { name: '操作说明', exact: true }).fill(note)
}
try {
  await page.goto(`${process.env.FRONTEND_URL || 'http://127.0.0.1:3100'}/defects?project_id=${pid}`)
  await page.getByRole('button', { name: '登记第一个缺陷', exact: true }).click(); await form.waitFor()
  await form.getByRole('button', { name: '保存缺陷', exact: true }).click()
  await form.getByText('请填写标题', { exact: true }).waitFor(); assert.equal(writes.length, 0)
  passed('空列表登记入口与必填校验')
  await form.getByRole('textbox', { name: '缺陷标题', exact: true }).fill('订单金额计算错误')
  await form.getByRole('textbox', { name: '缺陷描述', exact: true }).fill('优惠订单金额与规则不符')
  await form.getByRole('textbox', { name: '复现步骤 1', exact: true }).fill('登录')
  await form.getByRole('button', { name: '添加步骤', exact: true }).click()
  await form.getByRole('textbox', { name: '复现步骤 2', exact: true }).fill('提交订单')
  await form.getByRole('button', { name: '上移第 2 步', exact: true }).click()
  assert.equal(await form.getByRole('textbox', { name: '复现步骤 1', exact: true }).inputValue(), '提交订单')
  await select(form, '所属模块', '订单')
  await form.getByRole('button', { name: '保存并继续添加', exact: true }).click()
  await page.locator('.defect-row-highlight').waitFor()
  assert.deepEqual(writes[0].reproduce_steps, ['提交订单', '登录']); assert.match(writes[0].creation_request_id, /^[0-9a-f-]{36}$/)
  assert.equal(await form.getByRole('textbox', { name: '缺陷标题', exact: true }).inputValue(), '')
  passed('步骤排序、连续登记、编号生成与新增行高亮；兼容普通 HTTP')
  await form.getByRole('button', { name: '取消', exact: true }).click(); await form.waitFor({ state: 'hidden' })
  await page.getByRole('button', { name: '登记缺陷', exact: true }).click()
  await form.getByRole('textbox', { name: '缺陷标题', exact: true }).fill('订单金额计算错误')
  await form.getByRole('textbox', { name: '缺陷描述', exact: true }).fill('另一个待核对场景')
  await form.getByRole('button', { name: '保存缺陷', exact: true }).click()
  await page.getByRole('button', { name: '返回核对', exact: true }).click(); assert.equal(defects.length, 1)
  await form.getByRole('button', { name: '取消', exact: true }).click()
  await page.getByRole('button', { name: '继续编辑', exact: true }).click(); assert.equal(await form.isVisible(), true)
  await form.getByRole('button', { name: '取消', exact: true }).click(); await page.getByRole('button', { name: '放弃并离开', exact: true }).click()
  passed('同名提醒与未保存内容拦截')
  await page.getByRole('button', { name: '查看', exact: true }).click(); await drawer.waitFor()
  await action('完成分诊'); await dialog.getByRole('button', { name: '确认完成分诊', exact: true }).click(); await dialog.waitFor({ state: 'hidden' })
  await drawer.getByRole('button', { name: '指派责任人', exact: true }).click()
  await select(dialog, '流转处理人', '开发工程师'); await select(dialog, '流转验证人', '验证工程师')
  await dialog.getByRole('button', { name: '确认指派', exact: true }).click(); await dialog.waitFor({ state: 'hidden' })
  await action('开始处理'); await dialog.getByRole('button', { name: '确认开始处理', exact: true }).click(); await dialog.waitFor({ state: 'hidden' })
  passed('详情深链、分诊、指派与开始处理')
  await action('提交修复', '调整优惠规则')
  await dialog.getByRole('button', { name: '确认提交修复', exact: true }).click()
  await dialog.getByText('请选择验证人、填写修复版本或构建号，并确认修复可验证', { exact: true }).waitFor()
  assert.equal(defects[0].workflow_state, 'in_progress')
  await dialog.getByRole('textbox', { name: '修复构建号', exact: true }).fill('build-20261009')
  await dialog.locator('.el-checkbox').filter({ hasText: '确认修复已在被测环境中可验证' }).click()
  assert.equal(await dialog.getByRole('checkbox', { name: '确认修复已在被测环境中可验证', exact: true }).isChecked(), true)
  conflictOnce = true
  await dialog.getByRole('button', { name: '确认提交修复', exact: true }).click()
  await dialog.getByRole('button', { name: '刷新缺陷后重新核对', exact: true }).waitFor()
  assert.equal(await dialog.getByRole('textbox', { name: '修复构建号', exact: true }).inputValue(), 'build-20261009')
  await Promise.all([page.waitForResponse(response => response.url().endsWith('/api/defects/defect-1')), dialog.getByRole('button', { name: '刷新缺陷后重新核对', exact: true }).click()])
  await dialog.getByRole('button', { name: '确认提交修复', exact: true }).click(); await dialog.waitFor({ state: 'hidden' })
  passed('修复必要信息校验、409 冲突保留输入后核对重试')
  await action('验证通过', '优惠及边界场景回归通过')
  await dialog.getByRole('textbox', { name: '验证构建号', exact: true }).fill('build-20261009')
  await dialog.getByRole('button', { name: '确认验证通过', exact: true }).click(); await dialog.waitFor({ state: 'hidden' })
  await action('关闭缺陷'); await dialog.getByRole('button', { name: '确认关闭缺陷', exact: true }).click(); await dialog.waitFor({ state: 'hidden' })
  await action('重开缺陷', '新增输入再次暴露问题'); await dialog.getByRole('button', { name: '确认重开缺陷', exact: true }).click(); await dialog.waitFor({ state: 'hidden' })
  assert.equal(defects[0].workflow_state, 'reopened'); assert.deepEqual(defects[0].reproduce_steps, ['提交订单', '登录'])
  passed('验证、关闭与重开完整闭环；步骤不被操作备注污染')
  await drawer.getByRole('tab', { name: '活动历史', exact: true }).click()
  await drawer.getByText('调整优惠规则', { exact: true }).waitFor()
  assert.match(await drawer.innerText(), /开发工程师/)
  await drawer.getByRole('tab', { name: '检测证据', exact: true }).click()
  await drawer.getByText('手工登记的缺陷没有自动检测记录', { exact: true }).waitFor()
  passed('活动说明、人名解析及手工缺陷证据空态')
  await drawer.getByRole('button', { name: '编辑缺陷', exact: true }).click(); await form.waitFor()
  await form.getByRole('textbox', { name: '缺陷描述', exact: true }).fill('我的新增业务证据')
  conflictOnce = true; await form.getByRole('button', { name: '保存修改', exact: true }).click()
  await form.getByRole('button', { name: '核对最新修改', exact: true }).waitFor()
  assert.equal(await form.getByRole('textbox', { name: '缺陷描述', exact: true }).inputValue(), '我的新增业务证据')
  await form.getByRole('button', { name: '核对最新修改', exact: true }).click()
  await page.getByText(/其他成员已补充证据/).last().waitFor()
  await page.getByRole('button', { name: '保留输入并重新核对', exact: true }).click()
  await form.getByRole('button', { name: '保存修改', exact: true }).click(); await form.waitFor({ state: 'hidden' })
  assert.equal(defects[0].description, '我的新增业务证据')
  passed('编辑冲突展示他人最新修改，明确确认后保留本地输入并重试')
  const closeButton = drawer.locator('.el-drawer__close-btn')
  assert.ok(await closeButton.getAttribute('aria-label'))
  await closeButton.click(); await drawer.waitFor({ state: 'hidden' })
  await page.locator('.el-radio-button').filter({ hasText: '分诊队列' }).click()
  await page.getByText('没有符合筛选条件的缺陷', { exact: true }).waitFor()
  await page.getByRole('button', { name: '清除筛选', exact: true }).click(); await page.getByRole('button', { name: '查看', exact: true }).waitFor()
  failListing = true; await page.getByRole('button', { name: '刷新', exact: true }).click()
  await page.getByText('缺陷列表加载失败，请重试', { exact: true }).waitFor()
  failListing = false; await page.getByRole('button', { name: '重试', exact: true }).click(); await page.getByRole('button', { name: '查看', exact: true }).waitFor()
  passed('内置队列真实筛选与加载失败重试')
  await page.setViewportSize({ width: 390, height: 844 })
  await page.getByRole('button', { name: '登记缺陷', exact: true }).click(); await form.waitFor()
  await page.waitForFunction(() => { const box = document.querySelector('.defect-form-drawer')?.getBoundingClientRect(); return box && box.left >= -1 && box.right <= innerWidth + 1 })
  assert.equal(await form.evaluate(element => element.scrollWidth > element.clientWidth + 2), false)
  assert.equal(await form.evaluate(element => element.contains(document.elementFromPoint(24, 100))), true)
  await mkdir('test-results', { recursive: true }); await page.screenshot({ path: 'test-results/defects-mobile.png', fullPage: true })
  passed('移动端表单无横向溢出')
  assert.deepEqual(errors, []); console.log(`${checks} browser checks passed; no page errors`)
} catch (error) {
  console.error('PAGE ERRORS', errors); console.error((await page.locator('body').innerText()).slice(-5500))
  await mkdir('test-results', { recursive: true }); await page.screenshot({ path: 'test-results/defects-failure.png', fullPage: true }); throw error
} finally { await browser.close() }
