<template>
  <div class="case-library">
    <!-- 生成控制区 -->
    <el-card shadow="hover">
      <template #header>用例库 —— 草稿、评审、批准后进入 API 计划</template>
      <el-form label-width="80px" :inline="true">
        <el-form-item label="项目" required>
          <el-select v-model="projectId" placeholder="选择项目" filterable style="width: 220px" @change="onProjectChange">
            <el-option v-for="p in projects" :key="p.id" :label="p.name" :value="p.id" />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-button :loading="batchAdopting" :disabled="!selectedRows.length" @click="batchAdopt">批量批准待评审用例</el-button>
          <el-button
            type="primary"
            plain
            :disabled="selectedRows.length === 0 || selectedRows.some((r: any) => r.status !== 'adopted' || r.execution_kind === 'manual')"
            @click="openAddToPlan(selectedRows.map((r: any) => r.id))"
          >
            <el-icon><Files /></el-icon>
            加入计划（{{ selectedRows.length }}）
          </el-button>
          <el-button @click="loadCases" :loading="listLoading">刷新</el-button>
        </el-form-item>
      </el-form>
      <div class="kb-tip">
        用例来源：接口文档解析、需求文档解析、代码解析（测试流水线）AI 生成后自动汇聚于此；
        需求草稿先补齐真实 API 请求和断言，再提交评审；只有已批准的 API 用例能进入自动计划。
      </div>
    </el-card>

    <!-- 用例库 -->
    <el-card shadow="hover" style="margin-top: 16px" v-loading="listLoading">
      <template #header>
        用例库
        <span class="muted">（共 {{ totalCases }} 条，本页草稿 {{ draftCount }} 条）</span>
      </template>

      <el-tabs v-model="activeType" @tab-change="onFilterChange">
        <el-tab-pane label="全部" name="all" />
        <el-tab-pane label="需求/功能" name="functional" />
        <el-tab-pane label="正向" name="positive" />
        <el-tab-pane label="反向" name="negative" />
        <el-tab-pane label="边界" name="boundary" />
        <el-tab-pane label="异常" name="exception" />
      </el-tabs>

      <!-- 搜索 + 来源过滤 -->
      <div class="source-filter">
        <el-input
          v-model="searchKeyword"
          placeholder="搜索用例标题..."
          clearable
          style="width: 220px; margin-right: 12px"
          @keyup.enter="onFilterChange"
          @clear="onFilterChange"
        >
          <template #append>
            <el-button icon="Search" @click="onFilterChange" />
          </template>
        </el-input>
        <span class="filter-label" style="margin-left: 8px">来源：</span>
        <el-radio-group v-model="activeSource" size="small" @change="onFilterChange">
          <el-radio-button value="">全部</el-radio-button>
          <el-radio-button value="requirement">📄 需求生成</el-radio-button>
          <el-radio-button value="ai_generated">🤖 AI 接口生成</el-radio-button>
          <el-radio-button value="manual">👤 手工</el-radio-button>
        </el-radio-group>
        <span class="muted" style="margin-left: 12px">
          点 <b>需求生成</b> 一键筛选来源=requirement 的用例
        </span>
      </div>

      <el-table :data="cases" border @selection-change="onSelectionChange">
        <el-table-column type="selection" width="48" />
        <el-table-column prop="title" label="标题" min-width="200" show-overflow-tooltip />
        <el-table-column label="执行类型" width="95" align="center">
          <template #default="{ row }">{{ row.execution_kind === 'manual' ? '手工设计' : 'API' }}</template>
        </el-table-column>
        <el-table-column label="来源" width="110" align="center">
          <template #default="{ row }">
            <el-tag size="small" :type="sourceType(row.source)" effect="plain">
              {{ sourceLabel(row.source) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="接口" width="260">
          <template #default="{ row }">
            <span class="method-tag">{{ (row.request_data || {}).method || '-' }}</span>
            <span class="url-text">{{ (row.request_data || {}).url || '-' }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="priority" label="优先级" width="90" align="center">
          <template #default="{ row }">
            <el-tag size="small" :type="priorityType(row.priority)">{{ row.priority }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100" align="center">
          <template #default="{ row }">
            <el-tag size="small" :type="reviewTagType(row)">{{ reviewLabel(row) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="480" fixed="right">
          <template #default="{ row }">
            <el-button size="small" type="primary" plain :disabled="!['draft', 'changes_requested'].includes(row.review_state)" @click="submitReview(row)">提交评审</el-button>
            <el-button size="small" type="success" plain :disabled="row.review_state !== 'pending'" @click="adopt(row)">批准</el-button>
            <el-button size="small" type="warning" plain :disabled="row.review_state !== 'pending'" @click="requestChanges(row)">退回</el-button>
            <el-button size="small" type="warning" plain :disabled="row.status === 'deprecated'" @click="deprecate(row)">废弃</el-button>
            <el-button size="small" plain @click="openEdit(row)">编辑</el-button>
            <el-button size="small" plain @click="showReviewEvents(row)">记录</el-button>
            <el-button size="small" plain :disabled="row.status !== 'adopted' || row.execution_kind === 'manual'" @click="openAddToPlan([row.id])">
              <el-icon><Files /></el-icon>
              加入计划
            </el-button>
            <el-button size="small" type="danger" plain @click="deleteCase(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-pagination v-if="totalCases > pageSize" style="margin-top: 16px; justify-content: flex-end"
        v-model:current-page="page" :page-size="pageSize" :total="totalCases"
        layout="prev, pager, next, total" @current-change="loadCases" />
    </el-card>

    <!-- 编辑对话框 -->
    <el-dialog v-model="editVisible" title="编辑用例" width="640px" destroy-on-close>
      <el-form label-width="90px">
        <el-form-item label="标题">
          <el-input v-model="editForm.title" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="editForm.description" type="textarea" :rows="2" />
        </el-form-item>
        <el-form-item label="优先级">
          <el-select v-model="editForm.priority" style="width: 160px">
            <el-option label="P0" value="P0" />
            <el-option label="P1" value="P1" />
            <el-option label="P2" value="P2" />
            <el-option label="P3" value="P3" />
          </el-select>
        </el-form-item>
        <el-form-item label="执行类型">
          <el-select v-model="editForm.execution_kind" style="width: 180px">
            <el-option label="手工设计" value="manual" />
            <el-option label="API 自动执行" value="api" />
          </el-select>
        </el-form-item>
        <el-form-item label="请求数据">
          <el-input v-model="editForm.request_json" type="textarea" :rows="5" placeholder="JSON" />
        </el-form-item>
        <el-form-item label="预期结果">
          <el-input v-model="editForm.expected_json" type="textarea" :rows="4" placeholder="JSON" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button type="primary" :loading="savingEdit" @click="saveEdit">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="reviewEventsVisible" title="用例评审记录" width="620px">
      <el-timeline v-if="reviewEvents.length">
        <el-timeline-item v-for="event in reviewEvents" :key="event.id" :timestamp="event.created_at">
          {{ event.action }} · {{ event.actor_name || event.actor_id }}<div v-if="event.comment">{{ event.comment }}</div>
        </el-timeline-item>
      </el-timeline>
      <el-empty v-else description="尚无评审记录" />
    </el-dialog>

    <!-- P0 阶段7：加入计划弹窗（支持新建计划） -->
    <el-dialog
      v-model="addToPlanVisible"
      title="加入测试计划"
      width="560px"
      destroy-on-close
      @open="loadPlansIfNeeded"
    >
      <el-form label-width="80px">
        <el-form-item label="用例数量">
          <el-tag size="small" type="info">共 {{ addToPlanCaseIds.length }} 条用例</el-tag>
        </el-form-item>
        <el-form-item label="计划">
          <el-radio-group v-model="planMode">
            <el-radio-button value="existing">选择已有计划</el-radio-button>
            <el-radio-button value="new">新建计划</el-radio-button>
          </el-radio-group>
        </el-form-item>

        <template v-if="planMode === 'existing'">
          <el-form-item label="选择计划" required>
            <el-select
              v-model="targetPlanId"
              placeholder="选择测试计划"
              filterable
              clearable
              :loading="plansLoading"
              style="width: 100%"
            >
              <el-option
                v-for="p in plans"
                :key="p.id"
                :label="`${p.name}（${p.project_name || '—'}）`"
                :value="p.id"
              />
            </el-select>
          </el-form-item>
          <el-alert
            v-if="plans.length === 0 && !plansLoading"
            type="warning"
            :closable="false"
            show-icon
            title="当前还没有测试计划，请切换到「新建计划」直接创建"
          />
        </template>

        <template v-else>
          <el-form-item label="计划名称" required>
            <el-input
              v-model="newPlanName"
              placeholder="例如：订单中心回归测试"
              maxlength="200"
              show-word-limit
            />
          </el-form-item>
          <el-form-item label="备注">
            <el-input
              v-model="newPlanDesc"
              type="textarea"
              :rows="2"
              placeholder="计划用途说明（可选）"
              maxlength="500"
            />
          </el-form-item>
          <el-alert
            type="info"
            :closable="false"
            show-icon
            :title="`新计划将归属当前项目「${currentProjectName || '未选择'}」，创建后可在「测试任务 → 测试计划」页一键执行`"
          />
        </template>
      </el-form>
      <template #footer>
        <el-button @click="addToPlanVisible = false">取消</el-button>
        <el-button
          type="primary"
          :loading="addToPlanLoading"
          :disabled="planMode === 'existing' && !targetPlanId"
          @click="submitAddToPlan"
        >
          {{ planMode === 'new' ? '创建并加入' : '加入' }}
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Files } from '@element-plus/icons-vue'
import { caseApi, planApi, projectApi } from '@/api'

const route = useRoute()
const projects = ref<any[]>([])
const projectId = ref<string>('')

const listLoading = ref(false)
const batchAdopting = ref(false)

const cases = ref<any[]>([])
const totalCases = ref(0)
const page = ref(1)
const pageSize = 50
const activeType = ref<string>('all')
const activeSource = ref<string>('')  // v1.4：来源过滤（''=全部 / requirement / ai_generated / manual）
const searchKeyword = ref<string>('')  // 搜索关键字
const selectedRows = ref<any[]>([])

// P0 阶段7：「加入计划」弹窗状态
const addToPlanVisible = ref(false)
const addToPlanLoading = ref(false)
const addToPlanCaseIds = ref<string[]>([])
const plans = ref<any[]>([])
const plansLoading = ref(false)
const targetPlanId = ref<string>('')
const planMode = ref<'existing' | 'new'>('existing')
const newPlanName = ref<string>('')
const newPlanDesc = ref<string>('')

// R1：快捷新建项目
const SOURCE_LABELS: Record<string, string> = {
  requirement: '需求生成',
  ai_generated: 'AI 生成',
  manual: '手工',
}
const SOURCE_TYPES: Record<string, any> = {
  requirement: 'warning',   // 橙——需求驱动给人「半成品待确认」感
  ai_generated: 'primary',  // 蓝——AI 主线
  manual: 'success',        // 绿——已审定
}

const editVisible = ref(false)
const savingEdit = ref(false)
const editForm = ref<any>({})
const editId = ref<string>('')
const reviewEventsVisible = ref(false)
const reviewEvents = ref<any[]>([])

const STATUS_LABELS: Record<string, string> = {
  draft: '草稿',
  adopted: '已采纳',
  deprecated: '已废弃',
}
const PRIORITY_TYPES: Record<string, any> = {
  P0: 'danger',
  P1: 'warning',
  P2: '',
  P3: 'info',
}

function statusLabel(s: string): string {
  return STATUS_LABELS[s] || s || '-'
}
function reviewLabel(row: any): string {
  if (row.status === 'deprecated') return '已废弃'
  return ({ draft: '草稿', pending: '待评审', approved: '已批准', changes_requested: '已退回' } as Record<string, string>)[row.review_state] || statusLabel(row.status)
}
function reviewTagType(row: any): any {
  if (row.status === 'deprecated') return 'danger'
  return ({ pending: 'warning', approved: 'success', changes_requested: 'danger' } as Record<string, string>)[row.review_state] || 'info'
}
function priorityType(p: string): any {
  return PRIORITY_TYPES[p] || 'info'
}
function sourceLabel(s: string): string {
  return SOURCE_LABELS[s] || s || '-'
}
function sourceType(s: string): any {
  return SOURCE_TYPES[s] || 'info'
}

const draftCount = computed(() => cases.value.filter((c) => c.status === 'draft').length)

async function loadProjects() {
  try {
    const res: any = await projectApi.getList()
    const d = res?.data ?? res
    projects.value = Array.isArray(d) ? d : d?.list || d?.items || []
  } catch {
    projects.value = []
  }
}

async function onProjectChange() {
  plans.value = []
  selectedRows.value = []
  page.value = 1
  await loadCases()
}

function onFilterChange(): void {
  page.value = 1
  loadCases()
}

async function loadCases() {
  if (!projectId.value) {
    cases.value = []
    totalCases.value = 0
    return
  }
  listLoading.value = true
  try {
    const res: any = await caseApi.list({
      project_id: projectId.value,
      page: page.value,
      page_size: pageSize,
      case_type: activeType.value === 'all' ? undefined : activeType.value,
      source: activeSource.value || undefined,  // ''→不过滤；非空→传后端
      keyword: searchKeyword.value || undefined,  // 搜索关键字
    })
    cases.value = res?.data?.items || []
    totalCases.value = res?.data?.total || 0
  } catch {
    cases.value = []
    totalCases.value = 0
  } finally {
    listLoading.value = false
  }
}

function onSelectionChange(rows: any[]) {
  selectedRows.value = rows
}

// ============ P0 阶段7：加入计划（支持新建计划） ============
const currentProjectName = computed(() => {
  return projects.value.find((p: any) => p.id === projectId.value)?.name || ''
})

async function loadPlansIfNeeded(): Promise<void> {
  if (plansLoading.value) return
  if (plans.value.length === 0) {
    await loadPlans()
    if (plans.value.length === 0) planMode.value = 'new'
  }
}

async function loadPlans(): Promise<void> {
  plansLoading.value = true
  try {
    const res: any = await planApi.list({ project_id: projectId.value, page: 1, page_size: 200 })
    const list = res?.data?.list || res?.data?.items || res?.list || []
    plans.value = Array.isArray(list) ? list : []
  } catch {
    plans.value = []
  } finally {
    plansLoading.value = false
  }
}

function openAddToPlan(caseIds: string[]): void {
  if (!caseIds || caseIds.length === 0) {
    ElMessage.warning('请先选择至少一条用例')
    return
  }
  const chosen = cases.value.filter((c) => caseIds.includes(c.id))
  if (chosen.some((c) => c.status !== 'adopted' || c.execution_kind === 'manual')) {
    ElMessage.warning('只有已批准的 API 用例可以加入自动计划')
    return
  }
  addToPlanCaseIds.value = [...caseIds]
  targetPlanId.value = ''
  planMode.value = 'existing'
  newPlanName.value = ''
  newPlanDesc.value = ''
  addToPlanVisible.value = true
}

async function submitAddToPlan(): Promise<void> {
  if (addToPlanCaseIds.value.length === 0) {
    ElMessage.warning('用例列表为空')
    return
  }
  let pid = targetPlanId.value
  let createdName = ''
  if (planMode.value === 'new') {
    const name = newPlanName.value.trim()
    if (name.length < 2) {
      ElMessage.warning('计划名称至少 2 个字符')
      return
    }
    if (!projectId.value) {
      ElMessage.warning('请先在页面顶部选择项目')
      return
    }
    addToPlanLoading.value = true
    try {
      const res: any = await planApi.create({
        name,
        description: newPlanDesc.value.trim() || undefined,
        project_id: projectId.value,
      })
      pid = res?.data?.id || ''
      createdName = name
    } catch {
      return // 创建失败（如重名 409），拦截器已提示
    } finally {
      addToPlanLoading.value = false
    }
    if (!pid) {
      ElMessage.error('创建计划失败：响应缺少计划 ID')
      return
    }
  } else if (!pid) {
    ElMessage.warning('请选择目标测试计划')
    return
  }

  addToPlanLoading.value = true
  try {
    await planApi.addCases(pid, addToPlanCaseIds.value)
    ElMessage.success(
      createdName
        ? `已创建计划「${createdName}」并加入 ${addToPlanCaseIds.value.length} 条用例`
        : `已加入计划：${addToPlanCaseIds.value.length} 条用例`,
    )
    addToPlanVisible.value = false
    selectedRows.value = []
  } catch {
    /* axios 拦截器已处理 */
  } finally {
    addToPlanLoading.value = false
  }
}

async function batchAdopt() {
  const ids = selectedRows.value.map((r) => r.id)
  if (!ids.length) {
    ElMessage.warning('请先勾选要接纳的用例')
    return
  }
  if (selectedRows.value.some((r) => r.review_state !== 'pending')) {
    ElMessage.warning('批量批准仅适用于待评审用例')
    return
  }
  batchAdopting.value = true
  try {
    await caseApi.adoptBatch(ids)
    ElMessage.success(`已批量接纳 ${ids.length} 条`)
    await loadCases()
  } catch {
    /* ignore */
  } finally {
    batchAdopting.value = false
  }
}

async function adopt(row: any) {
  try {
    await caseApi.review(row.id, 'approve')
    ElMessage.success('评审已批准')
    await loadCases()
  } catch {
    /* ignore */
  }
}

async function submitReview(row: any) {
  try {
    await caseApi.submitReview(row.id)
    ElMessage.success('已提交评审')
    await loadCases()
  } catch { /* 拦截器已提示 */ }
}

async function requestChanges(row: any) {
  try {
    const result = await ElMessageBox.prompt('填写需要修改的内容', '退回用例', {
      inputValidator: (value: string) => !!value.trim() || '请填写修改意见',
    })
    await caseApi.review(row.id, 'changes_requested', result.value)
    ElMessage.success('已退回')
    await loadCases()
  } catch { /* 取消或请求失败 */ }
}

async function showReviewEvents(row: any) {
  try {
    const result: any = await caseApi.reviewEvents(row.id)
    reviewEvents.value = result?.data || []
    reviewEventsVisible.value = true
  } catch { /* 拦截器已提示 */ }
}

async function deprecate(row: any) {
  try {
    await ElMessageBox.confirm(`确认废弃用例「${row.title}」？`, '废弃确认', {
      type: 'warning',
      confirmButtonText: '废弃',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  try {
    await caseApi.deprecate(row.id)
    ElMessage.success('已废弃')
    await loadCases()
  } catch {
    /* ignore */
  }
}

async function deleteCase(row: any) {
  try {
    await ElMessageBox.confirm(`确认删除用例「${row.title}」？此操作不可恢复！`, '删除确认', {
      type: 'error',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  try {
    await caseApi.remove(row.id)
    ElMessage.success('已删除')
    await loadCases()
  } catch {
    /* ignore */
  }
}

function openEdit(row: any) {
  editId.value = row.id
  editForm.value = {
    title: row.title || '',
    description: row.description || '',
    priority: row.priority || 'P2',
    execution_kind: row.execution_kind || 'api',
    request_json: JSON.stringify(row.request_data || {}, null, 2),
    expected_json: JSON.stringify(row.expected_result || {}, null, 2),
  }
  editVisible.value = true
}

async function saveEdit() {
  let request_data: any
  let expected_result: any
  try {
    request_data = JSON.parse(editForm.value.request_json || '{}')
    expected_result = JSON.parse(editForm.value.expected_json || 'null')
  } catch {
    ElMessage.error('请求数据 / 预期结果 必须是合法 JSON')
    return
  }
  savingEdit.value = true
  try {
    await caseApi.update(editId.value, {
      title: editForm.value.title,
      description: editForm.value.description,
      priority: editForm.value.priority,
      execution_kind: editForm.value.execution_kind,
      request_data,
      expected_result,
    })
    ElMessage.success('保存成功')
    editVisible.value = false
    await loadCases()
  } catch {
    /* ignore */
  } finally {
    savingEdit.value = false
  }
}

onMounted(async () => {
  await loadProjects()
  // 支持从接口文档解析/评审页跳转：?project_id= 直达该项目
  const pid = (route.query.project_id as string) || ''
  if (pid && projects.value.some((p: any) => p.id === pid)) {
    projectId.value = pid
    onProjectChange()
  }
})
</script>

<style scoped>
.source-filter {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
  margin-bottom: 12px;
  padding: 8px 12px;
  background: var(--el-fill-color-lighter);
  border-radius: 4px;
  border: 1px solid var(--el-border-color-lighter);
}
.filter-label {
  color: var(--el-text-color-regular);
  font-size: 13px;
  font-weight: 600;
}

.muted {
  color: var(--el-text-color-secondary);
  font-size: 13px;
  font-weight: normal;
}
.method-tag {
  display: inline-block;
  font-weight: 600;
  color: var(--el-color-primary);
  margin-right: 6px;
}
.url-text {
  font-family: monospace;
  font-size: 12px;
  color: var(--el-text-color-regular);
  word-break: break-all;
}

.kb-tip {
  margin-top: 4px;
  padding: 8px 12px;
  background: var(--app-accent-weak);
  border-radius: 4px;
  font-size: 12px;
  color: var(--el-text-color-regular);
  line-height: 1.8;
}
.kb-tip a {
  color: var(--el-color-primary);
  text-decoration: none;
}
</style>
