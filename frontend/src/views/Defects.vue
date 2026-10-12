<template>
  <div class="defect-workspace">
    <div class="page-heading"><div><h2><el-icon><Warning /></el-icon> 缺陷中心</h2><p>分诊、处理、验证与回归，让每个问题都有责任人和完整记录。</p></div><div class="heading-actions"><el-button :icon="DataAnalysis" :disabled="!filters.project_id" @click="managementVisible = true">指标与管理</el-button><el-button v-if="canWrite" type="primary" :icon="Plus" @click="openCreate">登记缺陷</el-button></div></div>
    <div class="metric-grid"><el-card v-for="metric in metrics" :key="metric.label" shadow="never"><span>{{ metric.label }}</span><strong>{{ loadError ? '—' : metric.value }}</strong><small>{{ metric.hint }}</small></el-card></div>
    <el-card shadow="never" class="defect-list-card">
      <div class="filters">
        <el-select v-model="filters.project_id" filterable clearable placeholder="全部可访问项目" aria-label="缺陷项目筛选" @change="projectChanged"><el-option v-for="project in projects" :key="project.id" :value="project.id" :label="project.name" /></el-select>
        <el-input v-model="filters.q" placeholder="搜索编号、标题或描述" aria-label="搜索缺陷" :prefix-icon="Search" clearable @keyup.enter="reload" @clear="reload" />
        <el-select v-model="filters.workflow_state" clearable placeholder="全部状态" aria-label="缺陷状态筛选" @change="reload"><el-option v-for="item in workflowStateOptions" :key="item.key" :value="item.key" :label="item.label" /></el-select>
        <el-select v-model="filters.severity" clearable placeholder="严重程度" aria-label="严重程度筛选" @change="reload"><el-option v-for="(label, key) in severityLabels" :key="key" :value="key" :label="`${key} · ${label}`" /></el-select>
        <el-button :icon="Filter" @click="advanced = !advanced">更多筛选</el-button><el-button :icon="Refresh" :loading="loading" @click="reload">刷新</el-button>
      </div>
      <div v-if="advanced" class="advanced-filters">
        <el-select v-model="filters.priority" clearable placeholder="优先级" aria-label="优先级筛选" @change="reload"><el-option v-for="(label, key) in defectPriorities" :key="key" :value="key" :label="label" /></el-select>
        <el-select v-model="filters.defect_type" clearable placeholder="缺陷类型" aria-label="缺陷类型筛选" @change="reload"><el-option v-for="(label, key) in defectTypes" :key="key" :value="key" :label="label" /></el-select>
        <el-select v-model="filters.assignee_id" :disabled="!filters.project_id" filterable clearable placeholder="处理人（先选项目）" aria-label="处理人筛选" @change="reload"><el-option v-for="item in participants" :key="item.id" :value="item.id" :label="item.username" /></el-select>
        <el-select v-model="filters.verifier_id" :disabled="!filters.project_id" filterable clearable placeholder="验证人" aria-label="验证人筛选" @change="reload"><el-option v-for="item in participants" :key="item.id" :value="item.id" :label="item.username" /></el-select>
        <el-select v-model="filters.module_id" :disabled="!filters.project_id" filterable clearable placeholder="所属模块" aria-label="模块筛选" @change="reload"><el-option v-for="item in metadata.modules" :key="item.id" :value="item.id" :label="item.path" /></el-select>
        <el-select v-model="filters.iteration_id" :disabled="!filters.project_id" filterable clearable placeholder="所属迭代" aria-label="迭代筛选" @change="reload"><el-option v-for="item in metadata.iterations" :key="item.id" :value="item.id" :label="item.name" /></el-select>
        <el-select v-model="filters.environment_profile_id" :disabled="!filters.project_id" filterable clearable placeholder="环境" aria-label="环境筛选" @change="reload"><el-option v-for="item in metadata.environments" :key="item.id" :value="item.id" :label="item.name" /></el-select>
        <el-select v-model="filters.source" clearable placeholder="发现来源" aria-label="来源筛选" @change="reload"><el-option label="手工登记" value="manual" /><el-option label="自动测试发现" value="pipeline" /><el-option label="导入" value="import" /></el-select>
        <el-input v-model="filters.label" clearable placeholder="标签" aria-label="标签筛选" @keyup.enter="reload" @clear="reload" />
        <el-date-picker v-model="createdRange" type="datetimerange" range-separator="至" start-placeholder="创建开始" end-placeholder="创建结束" aria-label="创建时间范围" @change="reload" />
        <el-checkbox v-model="watching" :disabled="!filters.project_id" @change="reload">我关注的</el-checkbox>
        <el-button link @click="clearFilters">清除筛选</el-button>
      </div>
      <el-alert v-if="filters.test_run_id" title="当前按测试运行筛选，展示该次自动测试发现的缺陷。" type="info" :closable="false" class="run-filter"><el-button link @click="filters.test_run_id = ''; reload()">取消运行筛选</el-button></el-alert>
      <div class="view-row"><el-radio-group v-model="view" @change="reload"><el-radio-button v-for="item in views" :key="item.key" :value="item.key">{{ item.label }}</el-radio-button></el-radio-group><el-button v-if="metadata.can_configure" link :icon="FolderOpened" @click="catalogVisible = true">项目目录</el-button><el-checkbox v-if="metadata.roles?.some((role: string) => ['project_manager', 'qa_lead'].includes(role))" v-model="includeDeleted" @change="reload">包含回收站</el-checkbox></div>
      <div v-if="selectedRows.length" class="batch-bar"><span>已选择 {{ selectedRows.length }} 条</span><el-button size="small" type="primary" :disabled="!filters.project_id || !canWrite" @click="batchVisible = true">批量处理</el-button><el-button size="small" @click="managementVisible = true">导出所选</el-button></div>
      <el-alert v-if="loadError" title="缺陷列表加载失败，请重试" type="error" :closable="false" show-icon><el-button link @click="load">重试</el-button></el-alert>
      <el-table v-else v-loading="loading" :data="rows" row-key="id" :row-class-name="rowClass" empty-text="暂无缺陷" class="defect-table" @selection-change="selectedRows = $event">
        <el-table-column type="selection" width="44" :selectable="(row: any) => !row.deleted_at && (!filters.project_id || row.project_id === filters.project_id)" />
        <el-table-column label="缺陷" min-width="290"><template #default="{ row }"><div class="title-cell"><el-button link type="primary" @click="openDetail(row)"><span class="defect-key">{{ row.defect_key }}</span></el-button><el-button link class="defect-title" @click="openDetail(row)">{{ row.title }}</el-button><div><el-tag v-if="row.deleted_at" type="danger" size="small">已删除</el-tag><el-tag v-for="label in row.labels.slice(0, 3)" :key="label" size="small" type="info">{{ label }}</el-tag></div></div></template></el-table-column>
        <el-table-column label="状态" width="105"><template #default="{ row }"><el-tag :type="defectStateColor(row.workflow_state)">{{ row.workflow_state_label }}</el-tag></template></el-table-column>
        <el-table-column label="严重程度" width="110"><template #default="{ row }"><el-tag :type="row.severity === 'P0' ? 'danger' : row.severity === 'P1' ? 'warning' : 'info'">{{ row.severity }} · {{ row.severity_label }}</el-tag></template></el-table-column>
        <el-table-column label="优先级" width="85"><template #default="{ row }"><span :class="{ urgent: row.priority === 'urgent' }">{{ row.priority_label }}</span></template></el-table-column>
        <el-table-column label="处理人" width="115"><template #default="{ row }">{{ row.assignee_name || '未指派' }}</template></el-table-column>
        <el-table-column label="项目 / 模块" min-width="145"><template #default="{ row }"><span>{{ row.project_name || '待归属' }}</span><small class="module-name">{{ row.module_name || '未归类' }}</small></template></el-table-column>
        <el-table-column label="更新时间" width="165"><template #default="{ row }">{{ defectTime(row.updated_at) }}</template></el-table-column>
        <el-table-column label="操作" width="175" fixed="right"><template #default="{ row }"><el-button link type="primary" @click="openDetail(row)">查看</el-button><el-button link type="primary" :disabled="!!row.deleted_at || !canWrite" @click="openDetail(row)">流转</el-button><span class="more-anchor"><el-dropdown trigger="click" @command="(command: string) => rowCommand(command, row)"><el-button link :icon="MoreFilled" :aria-label="`${row.defect_key} 更多操作`">更多</el-button><template #dropdown><el-dropdown-menu><el-dropdown-item command="edit" :disabled="!canWrite || !!row.deleted_at">编辑</el-dropdown-item><el-dropdown-item command="detail">查看活动与证据</el-dropdown-item><el-dropdown-item command="restore" v-if="row.deleted_at">恢复</el-dropdown-item><el-dropdown-item command="delete" v-else :disabled="!canManage">删除</el-dropdown-item></el-dropdown-menu></template></el-dropdown></span></template></el-table-column>
        <template #empty><el-empty v-if="!loading" :description="hasFilters ? '没有符合筛选条件的缺陷' : '项目暂无缺陷，可以登记测试中发现的问题'" :image-size="80"><el-button v-if="hasFilters" @click="clearFilters">清除筛选</el-button><el-button v-else-if="canWrite" type="primary" :icon="Plus" @click="openCreate">登记第一个缺陷</el-button></el-empty></template>
      </el-table>
      <div class="pagination"><span>共 {{ total }} 个缺陷</span><el-pagination v-model:current-page="page" :page-size="20" :total="total" layout="prev, pager, next" @current-change="load" /></div>
    </el-card>
    <DefectFormDrawer v-model="formVisible" :projects="projects" :project-id="filters.project_id" :record="editing" @saved="saved" @rebase="editing = $event" />
    <DefectDetailDrawer ref="detailRef" :model-value="detailVisible" :defect-id="detailId" @update:model-value="closeDetail" @edit="editRecord" @changed="load" />
    <DefectCatalogDialog v-model="catalogVisible" :project-id="filters.project_id" @changed="loadProjectOptions" />
    <DefectBatchDialog v-model="batchVisible" :project-id="filters.project_id" :records="selectedRows" :participants="participants" :metadata="metadata" @completed="reload" />
    <DefectManagementDialog v-model="managementVisible" :project-id="filters.project_id" :filters="managementFilters" :selected-ids="selectedRows.map(item => item.id)" :can-configure="!!metadata.can_configure" @apply-view="applySavedView" @refreshed="reload" />
  </div>
</template>
<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { DataAnalysis, Filter, FolderOpened, MoreFilled, Plus, Refresh, Search, Warning } from '@element-plus/icons-vue'
import { defectsApi, projectApi } from '@/api'
import { useAuthStore } from '@/stores'
import { defectPriorities, defectStateColor, defectStates, defectTime, defectTypes, severityLabels, type DefectRecord } from '@/types/defects'
import DefectFormDrawer from '@/components/defects/DefectFormDrawer.vue'
import DefectDetailDrawer from '@/components/defects/DefectDetailDrawer.vue'
import DefectCatalogDialog from '@/components/defects/DefectCatalogDialog.vue'
import DefectBatchDialog from '@/components/defects/DefectBatchDialog.vue'
import DefectManagementDialog from '@/components/defects/DefectManagementDialog.vue'
const route = useRoute(), router = useRouter(), auth = useAuthStore()
const filters = reactive({ project_id: '', q: '', workflow_state: '', severity: '', priority: '', defect_type: '', assignee_id: '', verifier_id: '', module_id: '', iteration_id: '', environment_profile_id: '', source: '', label: '', test_run_id: '' })
const rows = ref<DefectRecord[]>([]), total = ref(0), page = ref(1), projects = ref<any[]>([]), loading = ref(false), loadError = ref(false), advanced = ref(false), view = ref('all'), includeDeleted = ref(false), metadata = ref<any>({}), participants = ref<any[]>([])
const stats = ref<any>({ by_severity: {}, by_state: {}, backlog: 0, pending_verification: 0 }), formVisible = ref(false), editing = ref<DefectRecord | null>(null), detailId = ref(''), detailVisible = ref(false), detailRef = ref<InstanceType<typeof DefectDetailDrawer>>(), catalogVisible = ref(false), highlighted = ref('')
const batchVisible = ref(false), managementVisible = ref(false), selectedRows = ref<DefectRecord[]>([]), createdRange = ref<[Date, Date] | null>(null), watching = ref(false)
let generation = 0, optionsGeneration = 0, highlightTimer: ReturnType<typeof setTimeout> | undefined
const canWrite = computed(() => !['viewer', 'auditor'].includes(auth.user?.role || '') && (!filters.project_id || metadata.value.can_create === true))
const canManage = computed(() => filters.project_id ? metadata.value.roles?.some((role: string) => ['project_manager', 'qa_lead'].includes(role)) : ['admin', 'super_admin', 'test_manager'].includes(auth.user?.role || ''))
const views = [{ key: 'all', label: '全部' }, { key: 'triage', label: '分诊队列' }, { key: 'assigned_to_me', label: '分配给我' }, { key: 'reported_by_me', label: '我报告的' }, { key: 'verify_by_me', label: '待我验证' }, { key: 'overdue', label: '已逾期' }]
const workflowStateOptions = computed(() => metadata.value.states?.length ? metadata.value.states : Object.entries(defectStates).map(([key, label]) => ({ key, label })))
const managementFilters = computed(() => ({ ...Object.fromEntries(Object.entries(filters).filter(([key, value]) => key !== 'project_id' && !!value)), view: view.value !== 'all' ? view.value : undefined, watching: watching.value || undefined, created_from: createdRange.value?.[0]?.toISOString(), created_to: createdRange.value?.[1]?.toISOString() }))
const hasFilters = computed(() => Object.entries(filters).some(([key, value]) => key !== 'project_id' && !!value) || view.value !== 'all' || includeDeleted.value)
const metrics = computed(() => [{ label: '当前筛选积压', value: stats.value.backlog || 0, hint: '包含新建、处理中、待验证和重开' }, { label: '致命 / 严重缺陷', value: (stats.value.by_severity?.P0 || 0) + (stats.value.by_severity?.P1 || 0), hint: '当前筛选内 P0 与 P1' }, { label: '待验证', value: stats.value.pending_verification || 0, hint: '修复提交后仍需验证确认' }, { label: '筛选结果', value: total.value, hint: '包含手工登记和自动测试发现' }])
async function load() {
  const stamp = ++generation; loading.value = true; loadError.value = false
  try {
    const params: any = { page: page.value, page_size: 20, view: view.value }
    for (const [key, value] of Object.entries(filters)) if (value && key !== 'workflow_state') params[key] = value
    if (filters.workflow_state) params.workflow_states = filters.workflow_state
    if (createdRange.value) { params.created_from = createdRange.value[0].toISOString(); params.created_to = createdRange.value[1].toISOString() }
    if (watching.value) params.watching = true
    if (includeDeleted.value) params.include_deleted = true
    const response: any = await defectsApi.list(params)
    if (stamp !== generation) return
    rows.value = response.data.list; total.value = response.data.total; stats.value = response.data.stats
  } catch { if (stamp === generation) loadError.value = true } finally { if (stamp === generation) loading.value = false }
}
function reload() { page.value = 1; void load() }
async function loadProjectOptions() {
  const stamp = ++optionsGeneration; metadata.value = {}; participants.value = []
  if (!filters.project_id) return
  try { const [meta, people]: any = await Promise.all([defectsApi.metadata(filters.project_id), defectsApi.participants(filters.project_id)]); if (stamp !== optionsGeneration) return; metadata.value = meta.data; participants.value = people.data.items } catch {}
}
function projectChanged() { for (const key of ['assignee_id', 'verifier_id', 'module_id', 'iteration_id', 'environment_profile_id'] as const) filters[key] = ''; includeDeleted.value = false; selectedRows.value = []; void loadProjectOptions(); reload() }
function clearFilters() { for (const key of Object.keys(filters)) if (key !== 'project_id') (filters as any)[key] = ''; view.value = 'all'; includeDeleted.value = false; createdRange.value = null; watching.value = false; reload() }
function applySavedView(query: Record<string, any>) { clearFilters(); for (const [key, value] of Object.entries(query || {})) { if (key in filters) (filters as any)[key] = value; else if (key === 'view') view.value = String(value || 'all'); else if (key === 'watching') watching.value = !!value }; if (query.created_from && query.created_to) createdRange.value = [new Date(query.created_from), new Date(query.created_to)]; reload() }
function openCreate() { editing.value = null; formVisible.value = true }
function openDetail(row: DefectRecord) { void router.push({ path: `/defects/${row.id}`, query: filters.project_id ? { project_id: filters.project_id } : {} }) }
function closeDetail(value: boolean) { detailVisible.value = value; if (!value && route.params.id) void router.replace({ path: '/defects', query: filters.project_id ? { project_id: filters.project_id } : {} }) }
function editRecord(record: DefectRecord) { editing.value = record; formVisible.value = true }
async function rowCommand(command: string, row: DefectRecord) {
  if (command === 'detail') { openDetail(row); return }
  try {
    const response: any = await defectsApi.get(row.id); const record = response.data as DefectRecord
    if (command === 'edit') { if (!record.permissions.edit) { ElMessage.warning('没有编辑此缺陷的权限'); return }; editRecord(record) }
    if (command === 'delete') { if (!record.permissions.delete) { ElMessage.warning('没有删除此缺陷的权限'); return }; await ElMessageBox.confirm('缺陷将移入回收站，历史和运行证据保留。', '删除缺陷', { type: 'warning' }); await defectsApi.remove(record.id, record.row_version); reload() }
    if (command === 'restore') { await defectsApi.restore(record.id, record.row_version); reload() }
  } catch {}
}
async function saved(record: DefectRecord, created: boolean) {
  if (created) { for (const key of Object.keys(filters)) (filters as any)[key] = ''; filters.project_id = record.project_id; view.value = 'all'; includeDeleted.value = false; page.value = 1; void loadProjectOptions() }
  highlighted.value = record.id; if (highlightTimer) clearTimeout(highlightTimer); highlightTimer = setTimeout(() => { highlighted.value = '' }, 8000)
  await load(); await nextTick(); document.querySelector('.defect-row-highlight')?.scrollIntoView({ block: 'nearest', behavior: 'smooth' }); if (detailVisible.value) await detailRef.value?.reload()
}
function rowClass({ row }: any) { return row.id === highlighted.value ? 'defect-row-highlight' : '' }
function syncRoute() {
  if (route.params.id) { detailId.value = String(route.params.id); detailVisible.value = true }
  else detailVisible.value = false
  if (route.query.project_id && String(route.query.project_id) !== filters.project_id) { filters.project_id = String(route.query.project_id); void loadProjectOptions(); reload() }
  if (route.query.test_run_id) { filters.test_run_id = String(route.query.test_run_id); reload() }
}
watch(() => route.fullPath, syncRoute)
onBeforeUnmount(() => { generation++; optionsGeneration++; if (highlightTimer) clearTimeout(highlightTimer) })
onMounted(async () => { try { const response: any = await projectApi.getList({ page_size: 100 }); projects.value = response.data.list || response.data.items || [] } catch {} syncRoute(); void loadProjectOptions(); void load() })
</script>
<style scoped>
.page-heading{display:flex;justify-content:space-between;align-items:center;gap:16px;margin-bottom:22px}.page-heading h2{display:flex;align-items:center;gap:10px;font-size:23px;margin:0 0 8px}.page-heading p{color:var(--el-text-color-secondary);font-size:13px;margin:0;line-height:1.7}.heading-actions{display:flex;gap:10px}.metric-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:16px;margin-bottom:20px}.metric-grid span,.metric-grid small{display:block;color:var(--el-text-color-secondary)}.metric-grid span{font-size:13px}.metric-grid strong{display:block;font-size:27px;margin:10px 0}.metric-grid small{font-size:12px;line-height:1.6}.filters,.advanced-filters{display:flex;gap:10px;flex-wrap:wrap}.filters .el-select{width:155px}.filters .el-input{width:250px;flex:1;min-width:180px}.advanced-filters{padding:14px 0;border-bottom:1px solid var(--el-border-color-light)}.advanced-filters .el-select,.advanced-filters .el-input{width:170px}.advanced-filters :deep(.el-date-editor){width:350px}.view-row{display:flex;align-items:center;gap:16px;flex-wrap:wrap;margin:18px 0}.batch-bar{display:flex;align-items:center;gap:10px;padding:10px 12px;margin-bottom:10px;border-radius:7px;background:var(--el-color-primary-light-9);color:var(--el-color-primary)}.run-filter{margin-top:14px}.title-cell{display:flex;align-items:flex-start;flex-direction:column;gap:4px}.defect-key{font-family:Consolas,monospace;font-size:12px}.defect-title{white-space:normal;text-align:left;height:auto;line-height:1.5}.title-cell .el-tag{margin:2px 5px 2px 0}.module-name{display:block;color:var(--el-text-color-secondary);margin-top:6px;font-size:12px}.urgent{color:var(--el-color-danger);font-weight:600}.pagination{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-top:18px;font-size:13px;color:var(--el-text-color-secondary)}:deep(.defect-row-highlight){--el-table-tr-bg-color:var(--el-color-primary-light-9)}.more-anchor{margin-left:8px}
@media(max-width:1000px){.metric-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:600px){.page-heading{align-items:flex-start;flex-direction:column}.page-heading h2{font-size:21px}.metric-grid{gap:10px}.metric-grid small{display:none}.filters .el-select,.filters .el-input,.advanced-filters .el-select,.advanced-filters .el-input{width:100%;min-width:0;flex:auto}.view-row :deep(.el-radio-group){display:flex;flex-wrap:wrap;gap:5px}.pagination{flex-direction:column;align-items:flex-start}}
</style>
