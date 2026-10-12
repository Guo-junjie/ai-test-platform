<template>
  <el-drawer :model-value="modelValue" title="缺陷详情" size="min(1020px, 100vw)" class="defect-detail-drawer" @update:model-value="emit('update:modelValue', $event)">
    <div v-loading="loading" class="detail-body">
      <el-result v-if="error" icon="error" title="缺陷加载失败" :sub-title="error"><template #extra><el-button @click="load">重新加载</el-button></template></el-result>
      <template v-else-if="detail">
        <div class="detail-title"><div><span class="defect-key">{{ detail.defect_key }}</span><h2>{{ detail.title }}</h2></div><el-tag :type="defectStateColor(detail.workflow_state)" size="large">{{ detail.workflow_state_label }}</el-tag></div>
        <div class="detail-actions">
          <el-button v-if="detail.permissions.edit" :icon="Edit" @click="emit('edit', detail)">编辑缺陷</el-button>
          <el-button v-if="detail.permissions.assign" :icon="UserFilled" @click="showAction(null)">指派责任人</el-button>
          <el-button v-for="action in primaryActions" :key="action.action_id" type="primary" @click="showAction(action)">{{ action.label }}</el-button>
          <el-dropdown v-if="detail.transitions.length" trigger="click" @command="command"><el-button :icon="Switch">更多流转</el-button><template #dropdown><el-dropdown-menu><el-dropdown-item v-for="action in detail.transitions" :key="action.action_id" :command="action.action_id" :disabled="!action.allowed" :title="action.disabled_reason">{{ action.label }}{{ !action.allowed ? `（${action.disabled_reason}）` : '' }}</el-dropdown-item></el-dropdown-menu></template></el-dropdown>
          <el-button v-if="detail.permissions.delete" :icon="Delete" @click="remove">删除</el-button>
          <el-button :icon="Link" @click="openLink">复制详情链接</el-button>
        </div>
        <el-alert v-if="detail.deleted_at" title="该缺陷已删除，活动记录与运行证据保留。" type="warning" :closable="false"><el-button v-if="detail.permissions.restore" link type="primary" @click="restore">恢复缺陷</el-button></el-alert>
        <el-alert v-if="detail.legacy_information" :title="detail.legacy_information" type="info" :closable="false" class="legacy-alert" />
        <el-tabs v-model="tab" @tab-change="tabChanged">
          <el-tab-pane label="概览" name="overview">
            <div class="detail-grid">
              <div class="main-column">
                <section><h3>缺陷描述</h3><p class="pre">{{ detail.description }}</p></section>
                <section v-if="detail.preconditions"><h3>前置条件</h3><p class="pre">{{ detail.preconditions }}</p></section>
                <section><h3>复现步骤</h3><ol v-if="detail.reproduce_steps?.length" class="steps"><li v-for="(step, index) in detail.reproduce_steps" :key="index" class="pre">{{ step }}</li></ol><p v-else class="muted">尚未补充</p></section>
                <div class="results-grid"><section><h3>预期结果</h3><p class="pre">{{ detail.expected_result || '尚未补充' }}</p></section><section><h3>实际结果</h3><p class="pre">{{ detail.actual_result || '尚未补充' }}</p></section></div>
                <section v-if="detail.root_cause || detail.fix_suggestion" class="ai-card"><h3><el-icon><MagicStick /></el-icon> AI 分析建议</h3><p class="muted">建议供团队核对，不代表已确认根因或验证通过。</p><b v-if="detail.root_cause">根因建议</b><p class="pre">{{ detail.root_cause }}</p><b v-if="detail.fix_suggestion">修复建议</b><p class="pre">{{ detail.fix_suggestion }}</p></section>
                <section v-if="detail.resolution_note"><h3>解决说明</h3><p class="pre">{{ detail.resolution_note }}</p></section>
              </div>
              <aside class="field-column">
                <dl>
                  <dt>所属项目</dt><dd>{{ detail.project_name || '待确定归属' }}</dd>
                  <dt>严重程度</dt><dd><el-tag :type="detail.severity === 'P0' ? 'danger' : detail.severity === 'P1' ? 'warning' : 'info'">{{ detail.severity }} · {{ detail.severity_label }}</el-tag></dd>
                  <dt>优先级</dt><dd>{{ detail.priority_label }}</dd><dt>缺陷类型</dt><dd>{{ detail.defect_type_label }}</dd>
                  <dt>报告人</dt><dd>{{ detail.reporter_name || '历史未记录' }}</dd><dt>处理人</dt><dd>{{ detail.assignee_name || '未指派' }}</dd><dt>验证人</dt><dd>{{ detail.verifier_name || '未指定' }}</dd>
                  <dt>所属模块</dt><dd>{{ detail.module_name || '未归类' }}</dd><dt>所属迭代</dt><dd>{{ detail.iteration_name || '未指定' }}</dd>
                  <dt>测试环境</dt><dd>{{ detail.environment_snapshot?.name || '未记录' }}<small v-if="detail.environment_snapshot?.base_url">{{ detail.environment_snapshot.base_url }}</small></dd>
                  <dt>影响版本</dt><dd>{{ detail.affected_releases?.map((item: any) => item.name).join('、') || '未记录' }}</dd>
                  <dt>修复版本 / 构建</dt><dd>{{ detail.fix_release_name || detail.fix_build || '未记录' }}</dd><dt>验证版本 / 构建</dt><dd>{{ detail.verified_release_name || detail.verified_build || '未记录' }}</dd>
                  <dt>来源</dt><dd>{{ sourceLabels[detail.source] || detail.source }}</dd><dt>标签</dt><dd><el-tag v-for="label in detail.labels" :key="label" class="label-tag">{{ label }}</el-tag><span v-if="!detail.labels.length">未添加</span></dd>
                  <dt>创建时间</dt><dd>{{ defectTime(detail.created_at) }}</dd><dt>更新时间</dt><dd>{{ defectTime(detail.updated_at) }}</dd><dt>解决期限</dt><dd>{{ defectTime(detail.due_at) }}</dd>
                  <dt>修复提交</dt><dd>{{ defectTime(detail.fix_submitted_at) }}</dd><dt>验证通过</dt><dd>{{ defectTime(detail.resolved_at) }}</dd><dt>关闭时间</dt><dd>{{ defectTime(detail.closed_at) }}</dd><dt>重开次数</dt><dd>{{ detail.reopened_count }}</dd>
                </dl>
              </aside>
            </div>
          </el-tab-pane>
          <el-tab-pane label="评论与附件" name="collaboration"><DefectCollaboration :defect="detail" :active="tab === 'collaboration'" @changed="collaborationChanged" /></el-tab-pane>
          <el-tab-pane label="活动历史" name="events">
            <el-alert v-if="historyError" title="活动加载失败" type="error" :closable="false"><el-button link @click="loadEvents(true)">重试</el-button></el-alert>
            <el-timeline v-loading="historyLoading" class="activity"><el-timeline-item v-for="event in history" :key="event.id" :timestamp="defectTime(event.occurred_at)" placement="top"><div class="event-heading"><b>{{ event.actor_name }}</b><span>{{ eventLabels[event.event_type] || event.event_type }}</span><el-tag v-if="event.from_state && event.from_state !== event.to_state" size="small">{{ defectStates[event.from_state] }} → {{ defectStates[event.to_state] }}</el-tag></div><p v-if="event.note" class="pre">{{ event.note }}</p><p v-if="event.is_legacy" class="muted">迁移时保存的历史基线；不代表该时间发生了修复或验证。</p><div v-if="event.event_type !== 'created' && !event.is_legacy" class="changes"><div v-for="(change, key) in visibleChanges(event)" :key="key"><span>{{ defectFieldLabels[key] || key }}</span><del>{{ displayValue(change.before) }}</del><span>→ {{ displayValue(change.after) }}</span></div></div></el-timeline-item></el-timeline>
            <el-empty v-if="!historyLoading && !history.length && !historyError" description="暂无活动记录" /><el-button v-if="hasMore" :loading="historyLoading" @click="loadEvents(false)">加载更多活动</el-button>
          </el-tab-pane>
          <el-tab-pane label="检测证据" name="occurrences"><el-alert v-if="evidenceError" title="检测记录加载失败" type="error" :closable="false"><el-button link @click="loadEvidence">重试</el-button></el-alert><el-table :data="evidence" v-loading="evidenceLoading" empty-text="手工登记的缺陷没有自动检测记录"><el-table-column label="测试运行" min-width="160"><template #default="{ row }"><el-button link type="primary" @click="$router.push(`/runs/${row.test_run_id}`)">查看运行证据</el-button></template></el-table-column><el-table-column label="检测时间" min-width="170"><template #default="{ row }">{{ defectTime(row.observed_at) }}</template></el-table-column><el-table-column label="请求" min-width="180"><template #default="{ row }">{{ row.evidence_json?.method || '' }} {{ row.evidence_json?.path || '历史未记录' }}</template></el-table-column><el-table-column label="HTTP" width="85"><template #default="{ row }">{{ row.evidence_json?.status_code ?? '—' }}</template></el-table-column></el-table></el-tab-pane>
          <el-tab-pane label="关联对象" name="references"><div class="reference-header"><span class="muted">关联需求、用例和同项目缺陷，方便追踪回归范围。</span><el-button v-if="detail.permissions.edit" :icon="Plus" @click="openReferences">添加关联</el-button></div><el-table :data="detail.references" empty-text="尚未关联对象"><el-table-column label="类型" width="90"><template #default="{ row }">{{ referenceLabels[row.kind] }}</template></el-table-column><el-table-column prop="title_snapshot" label="对象" min-width="200" /><el-table-column label="操作" width="120"><template #default="{ row }"><el-button v-if="row.kind !== 'requirement'" link type="primary" @click="visitReference(row)">查看</el-button><el-button v-if="detail.permissions.edit" link type="danger" @click="removeReference(row)">移除</el-button></template></el-table-column></el-table></el-tab-pane>
        </el-tabs>
      </template>
    </div>
  </el-drawer>
  <DefectActionDialog v-if="detail" v-model="actionVisible" :record="detail" :action="selectedAction" @saved="changed" @refresh="load" />
  <el-dialog v-model="referenceVisible" title="添加关联对象" width="520px" :close-on-click-modal="false" class="defect-reference-dialog"><el-form label-position="top"><el-form-item label="关联类型"><el-select v-model="referenceKind" aria-label="关联类型" @change="referenceTarget = ''; referenceKey = ''"><el-option label="需求文档" value="requirement" /><el-option label="测试用例" value="case" /><el-option label="相关缺陷" value="defect" /></el-select></el-form-item><el-form-item label="关联对象"><el-select v-model="referenceTarget" filterable aria-label="关联对象"><el-option v-for="item in referenceChoices" :key="item.id" :label="item.title || item.filename || item.defect_key" :value="item.id" /></el-select></el-form-item><el-form-item v-if="referenceKind === 'requirement' && referenceItems.length" label="需求条目"><el-select v-model="referenceKey" clearable filterable aria-label="需求条目"><el-option v-for="item in referenceItems" :key="item.key" :label="item.title" :value="item.key" /></el-select></el-form-item></el-form><template #footer><el-button @click="referenceVisible = false">取消</el-button><el-button type="primary" :loading="referenceSaving" @click="saveReference">保存关联</el-button></template></el-dialog>
</template>
<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Delete, Edit, Link, MagicStick, Plus, Switch, UserFilled } from '@element-plus/icons-vue'
import { defectsApi } from '@/api'
import { defectFieldLabels, defectStateColor, defectStates, defectTime, type DefectAction, type DefectRecord } from '@/types/defects'
import DefectActionDialog from './DefectActionDialog.vue'
import DefectCollaboration from './DefectCollaboration.vue'
const props = defineProps<{ modelValue: boolean; defectId: string }>()
const emit = defineEmits(['update:modelValue', 'edit', 'changed'])
const router = useRouter(), detail = ref<DefectRecord | null>(null), loading = ref(false), error = ref(''), tab = ref('overview')
const actionVisible = ref(false), selectedAction = ref<DefectAction | null>(null), history = ref<any[]>([]), historyLoading = ref(false), historyError = ref(false), hasMore = ref(false), evidence = ref<any[]>([]), evidenceLoading = ref(false), evidenceError = ref(false)
const referenceVisible = ref(false), referenceSaving = ref(false), referenceKind = ref('requirement'), referenceTarget = ref(''), referenceKey = ref(''), referenceMetadata = ref<any>({}), referenceDefects = ref<any[]>([])
let generation = 0
const primaryActions = computed(() => detail.value?.transitions.filter(item => item.allowed && ['triage', 'start', 'resume', 'submit_fix', 'verify_pass', 'verify_fail', 'close', 'reopen'].includes(item.action_id)) || [])
const referenceLabels: Record<string, string> = { requirement: '需求', case: '用例', defect: '缺陷' }
const sourceLabels: Record<string, string> = { manual: '手工登记', pipeline: '自动测试发现', import: '导入' }
const eventLabels: Record<string, string> = { created: '登记了缺陷', updated: '修改了缺陷', assigned: '调整了责任人', triage: '完成分诊', start: '开始处理', submit_fix: '提交修复', verify_pass: '验证通过', verify_fail: '验证失败并重开', close: '关闭缺陷', reopen: '重开缺陷', resume: '继续处理', reject: '拒绝缺陷', return_to_queue: '退回待分配', deleted: '删除了缺陷', restored: '恢复了缺陷', reference_added: '添加了关联', reference_removed: '移除了关联', legacy_imported: '导入历史基线' }
watch(() => [props.modelValue, props.defectId], () => { if (props.modelValue && props.defectId) { tab.value = 'overview'; void load() } else ++generation }, { immediate: true })
async function load() {
  const stamp = ++generation; loading.value = true; error.value = ''
  try { const response: any = await defectsApi.get(props.defectId); if (stamp === generation) { detail.value = response.data; history.value = []; evidence.value = []; if (tab.value === 'events') await loadEvents(true); if (tab.value === 'occurrences') await loadEvidence() } }
  catch (failure: any) { if (stamp === generation) error.value = typeof failure.response?.data?.detail === 'string' ? failure.response.data.detail : '请确认权限或重试' }
  finally { if (stamp === generation) loading.value = false }
}
function showAction(action: DefectAction | null) { selectedAction.value = action; actionVisible.value = true }
function command(id: string) { const action = detail.value?.transitions.find(item => item.action_id === id); if (action?.allowed) showAction(action) }
function changed(record: DefectRecord) { detail.value = record; history.value = []; evidence.value = []; emit('changed', record); if (tab.value === 'events') void loadEvents(true) }
function collaborationChanged() { history.value = []; emit('changed', detail.value); }
async function remove() { if (!detail.value) return; try { await ElMessageBox.confirm('删除后将从普通列表隐藏，历史与检测证据保留，可从回收站恢复。', '删除缺陷', { type: 'warning' }); await defectsApi.remove(detail.value.id, detail.value.row_version); ElMessage.success('缺陷已移入回收站'); emit('changed'); await load() } catch {} }
async function restore() { if (!detail.value) return; try { const response: any = await defectsApi.restore(detail.value.id, detail.value.row_version); changed(response.data); ElMessage.success('缺陷已恢复') } catch {} }
async function openLink() {
  const link = window.location.origin + '/defects/' + props.defectId
  try { if (!navigator.clipboard) throw new Error('clipboard unavailable'); await navigator.clipboard.writeText(link); ElMessage.success('详情链接已复制') }
  catch { await ElMessageBox.alert(link, '缺陷详情链接', { confirmButtonText: '知道了' }) }
}
function tabChanged(name: string | number) { if (name === 'events' && !history.value.length) void loadEvents(true); if (name === 'occurrences') void loadEvidence() }
async function loadEvents(reset: boolean) {
  if (historyLoading.value) return; const id = props.defectId; historyLoading.value = true; historyError.value = false
  try { const response: any = await defectsApi.events(id, reset ? 0 : history.value[history.value.length - 1]?.sequence || 0); if (id !== props.defectId) return; history.value = reset ? response.data.items : [...history.value, ...response.data.items]; hasMore.value = response.data.has_more }
  catch { historyError.value = true } finally { historyLoading.value = false }
}
async function loadEvidence() {
  const id = props.defectId; evidenceLoading.value = true; evidenceError.value = false
  try { const response: any = await defectsApi.occurrences(id); if (id === props.defectId) evidence.value = response.data.items } catch { evidenceError.value = true } finally { evidenceLoading.value = false }
}
function visibleChanges(event: any): Record<string, any> { return Object.fromEntries(Object.entries(event.display_changes || event.changes || {}).filter(([key, value]: any) => defectFieldLabels[key] && value && 'before' in value)) }
function displayValue(value: any) { if (value == null || value === '') return '未设置'; if (Array.isArray(value)) return value.join('、') || '空'; if (typeof value === 'object') return '已更新'; return String(value) }
const referenceChoices = computed(() => referenceKind.value === 'requirement' ? referenceMetadata.value.requirements || [] : referenceKind.value === 'case' ? referenceMetadata.value.cases || [] : referenceDefects.value)
const referenceItems = computed(() => referenceMetadata.value.requirements?.find((item: any) => item.id === referenceTarget.value)?.items || [])
async function openReferences() {
  if (!detail.value) return
  try { const [meta, defects]: any = await Promise.all([defectsApi.metadata(detail.value.project_id), defectsApi.list({ project_id: detail.value.project_id, page_size: 100 })]); referenceMetadata.value = meta.data; referenceDefects.value = defects.data.list.filter((item: any) => item.id !== props.defectId); referenceTarget.value = ''; referenceKey.value = ''; referenceVisible.value = true } catch {}
}
async function saveReference() {
  if (!detail.value || !referenceTarget.value || referenceSaving.value) { if (!referenceTarget.value) ElMessage.warning('请选择关联对象'); return }
  referenceSaving.value = true
  try { const key = { requirement: 'requirement_doc_id', case: 'case_asset_id', defect: 'related_defect_id' }[referenceKind.value] as string; const payload: any = { kind: referenceKind.value, [key]: referenceTarget.value }; if (referenceKind.value === 'requirement') payload.requirement_item_key = referenceKey.value || null; const response: any = await defectsApi.addReference(detail.value.id, payload, detail.value.row_version); changed(response.data); referenceVisible.value = false; ElMessage.success('关联已添加') } catch {} finally { referenceSaving.value = false }
}
async function removeReference(row: any) { if (!detail.value) return; try { await ElMessageBox.confirm('确定移除该关联？缺陷和关联对象都会保留。', '移除关联'); const response: any = await defectsApi.removeReference(detail.value.id, row.id, detail.value.row_version); changed(response.data) } catch {} }
function visitReference(row: any) { if (row.kind === 'case') void router.push({ path: '/case-library', query: { project_id: detail.value?.project_id, case_id: row.case_asset_id } }); else void router.push(`/defects/${row.related_defect_id}`) }
defineExpose({ reload: load })
</script>
<style scoped>
.detail-title{display:flex;justify-content:space-between;align-items:flex-start;gap:18px}.detail-title h2{font-size:21px;line-height:1.5;margin:8px 0 16px}.defect-key{color:var(--el-text-color-secondary);font-family:Consolas,monospace}.detail-actions{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:20px}.detail-actions .el-button{margin-left:0}.detail-grid{display:grid;grid-template-columns:minmax(0,1fr) 280px;gap:24px}.field-column{background:var(--el-fill-color-lighter);border-radius:10px;padding:16px}.field-column dl{margin:0}.field-column dt{font-size:12px;color:var(--el-text-color-secondary);margin:12px 0 6px}.field-column dd{margin:0;overflow-wrap:anywhere;font-size:13px}.field-column small{display:block;font-size:12px;color:var(--el-text-color-secondary)}section{margin:8px 0 24px}h3{font-size:15px;margin:8px 0 12px}.pre{white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.8;margin:8px 0}.muted{color:var(--el-text-color-secondary);font-size:13px}.results-grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}.ai-card{padding:16px;border:1px solid var(--el-border-color-light);border-radius:10px}.ai-card h3{display:flex;align-items:center;gap:8px}.steps{padding-left:24px}.label-tag{margin:0 5px 5px 0}.legacy-alert{margin-bottom:12px}.event-heading{display:flex;align-items:center;gap:8px;flex-wrap:wrap}.activity{padding:16px}.changes>div{display:flex;gap:10px;margin-top:8px;flex-wrap:wrap;font-size:13px;overflow-wrap:anywhere}.changes del{color:var(--el-text-color-secondary)}.reference-header{display:flex;align-items:center;justify-content:space-between;margin:12px 0;gap:12px}.el-select{width:100%}
@media(max-width:750px){.detail-grid{grid-template-columns:1fr}.results-grid{grid-template-columns:1fr}.detail-title h2{font-size:18px}.field-column dl{display:grid;grid-template-columns:110px minmax(0,1fr);gap:10px}.field-column dt{margin:0}.reference-header{align-items:flex-start;flex-direction:column}:global(.defect-reference-dialog){width:calc(100vw - 24px)!important}}
</style>
