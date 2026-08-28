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
          <el-button @click="loadCases" :loading="listLoading">刷新</el-button>
        </el-form-item>
      </el-form>
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
        <el-table-column label="操作" width="260" fixed="right">
          <template #default="{ row }">
            <el-button size="small" type="success" plain :disabled="row.status === 'adopted'" @click="adopt(row)">采纳</el-button>
            <el-button size="small" type="warning" plain :disabled="row.status === 'deprecated'" @click="deprecate(row)">废弃</el-button>
            <el-button size="small" plain @click="openEdit(row)">编辑</el-button>
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
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { caseApi, docApi, projectApi } from '@/api'

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
</style>
