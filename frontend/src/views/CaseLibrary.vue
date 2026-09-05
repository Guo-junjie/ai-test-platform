<template>
  <div class="case-library">
    <!-- 生成控制区 -->
    <el-card shadow="hover">
      <template #header>AI 生成用例</template>
      <el-form label-width="80px" :inline="true">
        <el-form-item label="项目" required>
          <el-select v-model="projectId" placeholder="选择项目" filterable style="width: 220px" @change="onProjectChange">
            <el-option v-for="p in projects" :key="p.id" :label="p.name" :value="p.id" />
          </el-select>
          <el-button style="margin-left: 8px" @click="quickCreateVisible = true">+ 新建</el-button>
        </el-form-item>
        <el-form-item label="接口">
          <el-select
            v-model="selectedEndpointIds"
            multiple
            filterable
            collapse-tags
            placeholder="不选则按整项目生成"
            style="width: 360px"
            @visible-change="onEndpointVisible"
          >
            <el-option v-for="e in endpoints" :key="e.id" :label="`${e.method} ${e.path}`" :value="e.id" />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="generating" :disabled="!projectId" @click="generate">
            AI 生成用例
          </el-button>
          <el-button :loading="batchAdopting" :disabled="!hasDraft" @click="batchAdopt">批量采纳</el-button>
          <el-button
            type="primary"
            plain
            :disabled="selectedRows.length === 0"
            @click="openAddToPlan(selectedRows.map((r: any) => r.id))"
          >
            <el-icon><Files /></el-icon>
            加入计划（{{ selectedRows.length }}）
          </el-button>
          <el-button @click="loadCases" :loading="listLoading">刷新</el-button>
        </el-form-item>
      </el-form>
      <div class="kb-tip">
        💡 提示：将<a href="/knowledge" @click.prevent="$router.push('/knowledge')">测试规范、历史缺陷</a>沉淀到知识库并重建后，
        AI 生成用例与缺陷分析会自动参考团队经验，产出更贴合业务的用例。
      </div>
    </el-card>

    <!-- 用例库 -->
    <el-card shadow="hover" style="margin-top: 16px" v-loading="listLoading">
      <template #header>
        用例库
        <span class="muted">（共 {{ cases.length }} 条，草稿 {{ draftCount }} 条）</span>
      </template>

      <el-tabs v-model="activeType">
        <el-tab-pane label="全部" name="all" />
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
          @keyup.enter="loadCases"
          @clear="loadCases"
        >
          <template #append>
            <el-button icon="Search" @click="loadCases" />
          </template>
        </el-input>
        <span class="filter-label" style="margin-left: 8px">来源：</span>
        <el-radio-group v-model="activeSource" size="small" @change="loadCases">
          <el-radio-button value="">全部</el-radio-button>
          <el-radio-button value="requirement">📄 需求生成（{{ sourceCount.requirement }}）</el-radio-button>
          <el-radio-button value="ai_generated">🤖 AI 接口生成（{{ sourceCount.ai_generated }}）</el-radio-button>
          <el-radio-button value="manual">👤 手工（{{ sourceCount.manual }}）</el-radio-button>
        </el-radio-group>
        <span class="muted" style="margin-left: 12px">
          点 <b>需求生成</b> 一键筛选来源=requirement 的用例
        </span>
      </div>

      <el-table :data="filteredCases" border @selection-change="onSelectionChange">
        <el-table-column type="selection" width="48" />
        <el-table-column prop="title" label="标题" min-width="200" show-overflow-tooltip />
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
            <el-tag size="small" :type="statusType(row.status)">{{ statusLabel(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="360" fixed="right">
          <template #default="{ row }">
            <el-button size="small" type="success" plain :disabled="row.status === 'adopted'" @click="adopt(row)">采纳</el-button>
            <el-button size="small" type="warning" plain :disabled="row.status === 'deprecated'" @click="deprecate(row)">废弃</el-button>
            <el-button size="small" plain @click="openEdit(row)">编辑</el-button>
            <el-button size="small" plain @click="openAddToPlan([row.id])">
              <el-icon><Files /></el-icon>
              加入计划
            </el-button>
            <el-button size="small" type="danger" plain @click="deleteCase(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
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

    <!-- 快捷新建项目 -->
    <ProjectQuickCreate :visible="quickCreateVisible" @update:visible="quickCreateVisible = $event" @created="onQuickCreated" />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Files } from '@element-plus/icons-vue'
import { caseApi, docApi, planApi, projectApi } from '@/api'
import ProjectQuickCreate from '@/components/ProjectQuickCreate.vue'

const projects = ref<any[]>([])
const projectId = ref<string>('')
const endpoints = ref<any[]>([])
const selectedEndpointIds = ref<string[]>([])

const generating = ref(false)
const listLoading = ref(false)
const batchAdopting = ref(false)

const cases = ref<any[]>([])
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
const quickCreateVisible = ref(false)

async function onQuickCreated(project: any): Promise<void> {
  try {
    const res: any = await projectApi.getList()
    const d = res?.data ?? res
    projects.value = Array.isArray(d) ? d : d?.list || d?.items || []
  } catch {
    /* 保留旧列表 */
  }
  if (project?.id) {
    projectId.value = project.id
    onProjectChange()
  }
}

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

const STATUS_LABELS: Record<string, string> = {
  draft: '草稿',
  adopted: '已采纳',
  deprecated: '已废弃',
}
const STATUS_TYPES: Record<string, any> = {
  draft: 'info',
  adopted: 'success',
  deprecated: 'danger',
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
function statusType(s: string): any {
  return STATUS_TYPES[s] || 'info'
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

const filteredCases = computed(() => {
  let arr = cases.value
  if (activeType.value !== 'all') {
    arr = arr.filter((c) => c.case_type === activeType.value)
  }
  return arr
})
const draftCount = computed(() => cases.value.filter((c) => c.status === 'draft').length)
const hasDraft = computed(() => draftCount.value > 0)

/** 各来源计数（前端计算，避免 N 次请求） */
const sourceCount = computed(() => {
  const acc: Record<string, number> = { requirement: 0, ai_generated: 0, manual: 0 }
  for (const c of cases.value) {
    const s = c.source || 'ai_generated'  // 老数据无 source 字段默认归 ai_generated
    if (acc[s] === undefined) acc[s] = 0
    acc[s] += 1
  }
  return acc
})

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
  selectedEndpointIds.value = []
  endpoints.value = []
  await loadEndpoints()
  await loadCases()
}

async function onEndpointVisible(visible: boolean) {
  if (visible) await loadEndpoints()
}

async function loadEndpoints() {
  if (!projectId.value) {
    endpoints.value = []
    return
  }
  try {
    const res: any = await docApi.listEndpoints({
      project_id: projectId.value,
      page: 1,
      page_size: 200,
    })
    endpoints.value = res?.data?.items || []
  } catch {
    endpoints.value = []
  }
}

async function loadCases() {
  if (!projectId.value) {
    cases.value = []
    return
  }
  listLoading.value = true
  try {
    const res: any = await caseApi.list({
      project_id: projectId.value,
      page: 1,
      page_size: 200,
      source: activeSource.value || undefined,  // ''→不过滤；非空→传后端
      keyword: searchKeyword.value || undefined,  // 搜索关键字
    })
    cases.value = res?.data?.items || []
  } catch {
    cases.value = []
  } finally {
    listLoading.value = false
  }
}

async function generate() {
  if (!projectId.value) {
    ElMessage.warning('请先选择项目')
    return
  }
  generating.value = true
  try {
    const payload: any = { project_id: projectId.value }
    if (selectedEndpointIds.value.length) {
      payload.endpoint_ids = selectedEndpointIds.value
    }
    const res: any = await caseApi.generate(payload)
    const cnt = res?.data?.inserted ?? 0
    ElMessage.success(`生成完成，新增 ${cnt} 条用例`)
    await loadCases()
  } catch (e: any) {
    /* 拦截器已提示 */
  } finally {
    generating.value = false
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
    const res: any = await planApi.list({ page: 1, page_size: 200 })
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
    await caseApi.adopt(row.id)
    ElMessage.success('已接纳')
    await loadCases()
  } catch {
    /* ignore */
  }
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
  const route = useRoute()
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
  background: #fafafa;
  border-radius: 4px;
  border: 1px solid #ebeef5;
}
.filter-label {
  color: #606266;
  font-size: 13px;
  font-weight: 600;
}

.muted {
  color: #909399;
  font-size: 13px;
  font-weight: normal;
}
.method-tag {
  display: inline-block;
  font-weight: 600;
  color: #409eff;
  margin-right: 6px;
}
.url-text {
  font-family: monospace;
  font-size: 12px;
  color: #606266;
  word-break: break-all;
}

.kb-tip {
  margin-top: 4px;
  padding: 8px 12px;
  background: #f4f8ff;
  border-radius: 4px;
  font-size: 12px;
  color: #606266;
  line-height: 1.8;
}
.kb-tip a {
  color: #409eff;
  text-decoration: none;
}
</style>
