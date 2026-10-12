<template>
  <el-drawer v-model="visible" :title="record ? '编辑缺陷' : '登记缺陷'" size="min(780px, 100vw)" :before-close="beforeClose" :close-on-click-modal="false" class="defect-form-drawer">
    <el-form ref="formRef" :model="form" :rules="rules" label-position="top" v-loading="loading" @submit.prevent="save(false)">
      <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon class="form-alert"><el-button link type="primary" @click="loadOptions">重试加载</el-button></el-alert>
      <el-alert v-if="submitError" :title="submitError" type="error" :closable="false" show-icon class="form-alert"><el-button v-if="versionConflict" link type="primary" @click="reviewLatest">核对最新修改</el-button></el-alert>
      <div class="section-heading"><h3>基本信息</h3><el-button v-if="metadata.can_configure" link :icon="FolderOpened" @click="catalogVisible = true">管理项目目录</el-button></div>
      <el-form-item label="所属项目" prop="project_id"><el-select v-model="form.project_id" :disabled="!!record || saving" filterable placeholder="选择项目" aria-label="所属项目" @change="projectChanged"><el-option v-for="project in projects" :key="project.id" :label="project.name" :value="project.id" /></el-select></el-form-item>
      <el-alert v-if="form.project_id && !loading && !error && !metadata.can_create && !record" title="当前项目仅有查看权限，不能登记缺陷。" type="warning" :closable="false" class="form-alert" />
      <el-form-item label="缺陷标题" prop="title"><el-input v-model="form.title" aria-label="缺陷标题" maxlength="500" show-word-limit placeholder="描述在哪个场景发生了什么问题" @blur="checkDuplicates" /></el-form-item>
      <el-form-item label="缺陷描述" prop="description"><el-input v-model="form.description" aria-label="缺陷描述" type="textarea" :rows="3" maxlength="30000" placeholder="说明问题及对用户或业务的影响" /></el-form-item>
      <div class="form-grid">
        <el-form-item label="严重程度" prop="severity"><el-select v-model="form.severity" aria-label="严重程度"><el-option v-for="(label, key) in severityLabels" :key="key" :label="`${key} · ${label}`" :value="key" /></el-select></el-form-item>
        <el-form-item label="优先级" prop="priority"><el-select v-model="form.priority" :disabled="!!record && !privileged" aria-label="优先级"><el-option v-for="(label, key) in defectPriorities" :key="key" :label="label" :value="key" /></el-select><div class="field-hint">严重程度表示影响，优先级表示处理顺序。</div></el-form-item>
        <el-form-item label="缺陷类型"><el-select v-model="form.defect_type" aria-label="缺陷类型"><el-option v-for="(label, key) in defectTypes" :key="key" :label="label" :value="key" /></el-select></el-form-item>
        <el-form-item label="所属模块"><el-select v-model="form.module_id" clearable filterable aria-label="所属模块" placeholder="选择模块"><el-option v-for="item in metadata.modules" :key="item.id" :label="item.path" :value="item.id" :disabled="item.current_only" /></el-select></el-form-item>
        <el-form-item label="所属迭代"><el-select v-model="form.iteration_id" clearable filterable aria-label="所属迭代" placeholder="选择迭代"><el-option v-for="item in metadata.iterations" :key="item.id" :label="item.name" :value="item.id" :disabled="item.current_only" /></el-select></el-form-item>
        <el-form-item label="测试环境"><el-select v-model="form.environment_profile_id" clearable filterable aria-label="测试环境" placeholder="选择环境"><el-option v-for="item in metadata.environments" :key="item.id" :label="item.name" :value="item.id" :disabled="item.current_only" /></el-select></el-form-item>
      </div>
      <h3>复现与结果</h3>
      <el-form-item label="前置条件"><el-input v-model="form.preconditions" aria-label="前置条件" type="textarea" :rows="2" maxlength="10000" placeholder="账号、权限、准备数据等" /></el-form-item>
      <div class="section-heading"><b>复现步骤</b><el-button :icon="Plus" @click="form.reproduce_steps.push('')">添加步骤</el-button></div>
      <div v-for="(_, index) in form.reproduce_steps" :key="index" class="step-card">
        <div class="step-head"><span>步骤 {{ index + 1 }}</span><div><el-button text :icon="ArrowUp" :disabled="index === 0" :aria-label="`上移第 ${index + 1} 步`" @click="move(index, -1)" /><el-button text :icon="ArrowDown" :disabled="index === form.reproduce_steps.length - 1" :aria-label="`下移第 ${index + 1} 步`" @click="move(index, 1)" /><el-button text :icon="Delete" :aria-label="`删除第 ${index + 1} 步`" @click="form.reproduce_steps.splice(index, 1)" /></div></div>
        <el-input v-model="form.reproduce_steps[index]" :aria-label="`复现步骤 ${index + 1}`" type="textarea" :rows="2" maxlength="2000" placeholder="输入具体操作和必要的数据" />
      </div>
      <div class="form-grid"><el-form-item label="预期结果"><el-input v-model="form.expected_result" aria-label="预期结果" type="textarea" :rows="3" maxlength="10000" /></el-form-item><el-form-item label="实际结果"><el-input v-model="form.actual_result" aria-label="实际结果" type="textarea" :rows="3" maxlength="10000" /></el-form-item></div>
      <el-form-item label="复现概率"><el-select v-model="form.reproducibility" aria-label="复现概率"><el-option label="每次都出现" value="always" /><el-option label="偶尔出现" value="intermittent" /><el-option label="仅出现一次" value="once" /><el-option label="尚未确认" value="unknown" /></el-select></el-form-item>
      <h3>责任与关联</h3>
      <div class="form-grid">
        <el-form-item label="处理人"><el-select v-model="form.assignee_id" clearable filterable :disabled="!!record && (!privileged || !['new', 'unassigned', 'reopened'].includes(record.workflow_state))" aria-label="处理人" placeholder="由负责人指派"><el-option v-for="item in assignees" :key="item.id" :label="item.username" :value="item.id" :disabled="item.current_only" /></el-select></el-form-item>
        <el-form-item label="验证人"><el-select v-model="form.verifier_id" clearable filterable :disabled="!!record && (!privileged || !['new', 'unassigned', 'reopened'].includes(record.workflow_state))" aria-label="验证人" placeholder="选择测试验证人员"><el-option v-for="item in verifiers" :key="item.id" :label="item.username" :value="item.id" :disabled="item.current_only" /></el-select></el-form-item>
      </div>
      <el-form-item label="影响版本"><el-select v-model="form.affected_release_ids" multiple filterable aria-label="影响版本" placeholder="在哪些版本发现了问题"><el-option v-for="item in metadata.releases" :key="item.id" :label="item.name" :value="item.id" :disabled="item.current_only" /></el-select></el-form-item>
      <el-form-item label="标签"><el-select v-model="form.labels" multiple filterable allow-create default-first-option :multiple-limit="20" aria-label="缺陷标签" placeholder="输入后回车，可添加多个标签" /></el-form-item>
      <el-form-item label="解决期限"><el-date-picker v-model="form.due_at" type="datetime" aria-label="解决期限" placeholder="选填" /></el-form-item>
      <el-form-item v-if="!record" label="关联需求文档"><el-select v-model="requirementId" clearable filterable aria-label="关联需求文档" placeholder="选择本项目需求文档" @change="requirementKey = ''"><el-option v-for="item in metadata.requirements" :key="item.id" :label="item.filename" :value="item.id" :disabled="item.current_only" /></el-select></el-form-item>
      <el-form-item v-if="!record && requirementId && requirementItems.length" label="关联需求条目"><el-select v-model="requirementKey" clearable filterable aria-label="关联需求条目" placeholder="不选择则关联整个文档"><el-option v-for="item in requirementItems" :key="item.key" :label="`${item.key} · ${item.title}`" :value="item.key" /></el-select></el-form-item>
      <el-form-item v-if="!record" label="关联用例"><el-select v-model="caseIds" multiple filterable aria-label="关联用例" placeholder="选择本项目用例"><el-option v-for="item in metadata.cases" :key="item.id" :label="item.title" :value="item.id" :disabled="item.current_only" /></el-select></el-form-item>
      <el-form-item v-if="record" label="修改说明"><el-input v-model="form.note" aria-label="修改说明" type="textarea" :rows="2" maxlength="5000" /></el-form-item>
      <el-alert v-if="duplicates.length" type="warning" :closable="false" title="发现同名缺陷，请确认是否为同一问题" class="form-alert"><div v-for="item in duplicates" :key="item.id"><a :href="`/defects/${item.id}`" target="_blank" rel="noopener">{{ item.defect_key }} · {{ item.title }}</a></div></el-alert>
    </el-form>
    <template #footer><div class="drawer-footer"><el-button :disabled="saving" @click="close">取消</el-button><el-button v-if="!record" :disabled="!canSave" :loading="saving && continuing" @click="save(true)">保存并继续添加</el-button><el-button type="primary" :icon="Check" :disabled="!canSave" :loading="saving && !continuing" @click="save(false)">{{ record ? '保存修改' : '保存缺陷' }}</el-button></div></template>
  </el-drawer>
  <DefectCatalogDialog v-model="catalogVisible" :project-id="form.project_id" @changed="loadOptions" />
</template>
<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { onBeforeRouteLeave, onBeforeRouteUpdate } from 'vue-router'
import { ElMessage, ElMessageBox, type FormInstance } from 'element-plus'
import { ArrowDown, ArrowUp, Check, Delete, FolderOpened, Plus } from '@element-plus/icons-vue'
import { defectsApi } from '@/api'
import { defectFieldLabels, defectPriorities, defectTypes, severityLabels, type DefectRecord } from '@/types/defects'
import DefectCatalogDialog from './DefectCatalogDialog.vue'
import { createRequestId } from '@/utils/requestId'
const props = defineProps<{ modelValue: boolean; projects: any[]; projectId?: string; record?: DefectRecord | null }>()
const emit = defineEmits(['update:modelValue', 'saved', 'rebase'])
const visible = computed({ get: () => props.modelValue, set: value => emit('update:modelValue', value) })
const blank = () => ({ project_id: props.projectId || '', title: '', description: '', severity: 'P2', priority: 'normal', defect_type: 'business', module_id: '', iteration_id: '', environment_profile_id: '', preconditions: '', expected_result: '', actual_result: '', reproduce_steps: [''], reproducibility: 'unknown', assignee_id: '', verifier_id: '', labels: [] as string[], affected_release_ids: [] as string[], due_at: null as Date | null, note: '' })
const form = ref(blank()), formRef = ref<FormInstance>(), metadata = ref<any>({}), assignees = ref<any[]>([]), verifiers = ref<any[]>([])
const loading = ref(false), saving = ref(false), continuing = ref(false), error = ref(''), duplicates = ref<any[]>([]), catalogVisible = ref(false)
const submitError = ref(''), versionConflict = ref(false)
const requirementId = ref(''), requirementKey = ref(''), caseIds = ref<string[]>([]), requestId = ref(createRequestId())
const baseline = ref('')
let generation = 0, lastProject = '', lastPayload = ''
const serialized = computed(() => JSON.stringify({ form: form.value, requirement: requirementId.value, key: requirementKey.value, cases: caseIds.value }))
const dirty = computed(() => visible.value && serialized.value !== baseline.value)
const privileged = computed(() => metadata.value.roles?.some((role: string) => ['project_manager', 'qa_lead'].includes(role)))
const canSave = computed(() => !!form.value.project_id && !loading.value && !error.value && !saving.value && !versionConflict.value && (props.record ? props.record.permissions.edit : metadata.value.can_create))
const requirementItems = computed(() => metadata.value.requirements?.find((item: any) => item.id === requirementId.value)?.items || [])
const required = (message: string) => ({ required: true, message, trigger: 'blur' })
const rules = { project_id: [required('请选择项目')], title: [required('请填写标题'), { min: 2, message: '标题至少 2 个字符', trigger: 'blur' }, { validator: (_: any, value: string, callback: any) => callback(value?.trim().length >= 2 ? undefined : new Error('标题不能只输入空格')), trigger: 'blur' }], description: [required('请填写描述'), { validator: (_: any, value: string, callback: any) => callback(value?.trim() ? undefined : new Error('描述不能只输入空格')), trigger: 'blur' }], severity: [required('请选择严重程度')], priority: [required('请选择优先级')] }
watch(() => props.modelValue, value => {
  if (!value) return
  form.value = blank(); requirementId.value = ''; requirementKey.value = ''; caseIds.value = []; duplicates.value = []; lastPayload = ''
  requestId.value = createRequestId()
  submitError.value = ''; versionConflict.value = false
  if (props.record) {
    for (const key of Object.keys(form.value)) if (key in props.record && key !== 'note') (form.value as any)[key] = props.record[key] ?? ((blank() as any)[key])
    form.value.reproduce_steps = [...(props.record.reproduce_steps || [])]; form.value.labels = [...(props.record.labels || [])]; form.value.affected_release_ids = [...(props.record.affected_release_ids || [])]
    form.value.due_at = props.record.due_at ? new Date(props.record.due_at) : null
  }
  lastProject = form.value.project_id; baseline.value = serialized.value; formRef.value?.clearValidate(); void loadOptions()
})
async function loadOptions() {
  const stamp = ++generation
  error.value = ''; metadata.value = {}; assignees.value = []; verifiers.value = []
  if (!form.value.project_id) { loading.value = false; return }
  loading.value = true
  try {
    const [meta, developers, testers]: any = await Promise.all([defectsApi.metadata(form.value.project_id), defectsApi.participants(form.value.project_id, 'assignee'), defectsApi.participants(form.value.project_id, 'verifier')])
    if (stamp !== generation) return
    metadata.value = meta.data; assignees.value = developers.data.items; verifiers.value = testers.data.items
    const record = props.record
    if (record) {
      const keepCurrent = (items: any[], id: string | null | undefined, name: string | null | undefined) => {
        if (id && !items.some(item => item.id === id)) items.push({ id, name: name || '历史关联', path: name || '历史关联', username: name || '历史人员', current_only: true })
      }
      keepCurrent(metadata.value.modules, record.module_id, record.module_name)
      keepCurrent(metadata.value.iterations, record.iteration_id, record.iteration_name)
      keepCurrent(metadata.value.environments, record.environment_profile_id, record.environment_snapshot?.name)
      keepCurrent(assignees.value, record.assignee_id, record.assignee_name)
      keepCurrent(verifiers.value, record.verifier_id, record.verifier_name)
      for (const release of record.affected_releases || []) keepCurrent(metadata.value.releases, release.id, release.name)
    }
  } catch { if (stamp === generation) error.value = '项目选项加载失败，请重试' } finally { if (stamp === generation) loading.value = false }
}
async function projectChanged() {
  if (lastProject && [form.value.module_id, form.value.iteration_id, form.value.environment_profile_id, form.value.assignee_id, requirementId.value, ...caseIds.value].some(Boolean)) {
    try { await ElMessageBox.confirm('更换项目将清空目录、环境、人员和关联对象，其他内容保留。', '更换所属项目', { confirmButtonText: '更换项目', cancelButtonText: '保留当前项目' }) }
    catch { form.value.project_id = lastProject; return }
  }
  for (const key of ['module_id', 'iteration_id', 'environment_profile_id', 'assignee_id', 'verifier_id'] as const) form.value[key] = ''
  form.value.affected_release_ids = []; requirementId.value = ''; requirementKey.value = ''; caseIds.value = []; duplicates.value = []; lastProject = form.value.project_id; await loadOptions()
}
function move(index: number, offset: number) { const steps = form.value.reproduce_steps; [steps[index], steps[index + offset]] = [steps[index + offset], steps[index]] }
async function checkDuplicates() {
  if (!form.value.project_id || form.value.title.trim().length < 2) { duplicates.value = []; return }
  const title = form.value.title.trim(), project = form.value.project_id
  try { const response: any = await defectsApi.duplicates(project, title, props.record?.id); if (form.value.project_id === project && form.value.title.trim() === title) duplicates.value = response.data.items } catch {}
}
let discard: Promise<boolean> | undefined
async function canLeave() {
  if (saving.value) { ElMessage.warning('正在保存，请稍候'); return false }
  if (!dirty.value) return true
  if (!discard) discard = ElMessageBox.confirm('缺陷内容尚未保存，离开后将丢失当前输入。', '放弃未保存内容？', { confirmButtonText: '放弃并离开', cancelButtonText: '继续编辑', type: 'warning' }).then(() => true, () => false).finally(() => { discard = undefined })
  return discard
}
async function beforeClose(done: () => void) { if (await canLeave()) done() }
async function close() { if (await canLeave()) visible.value = false }
onBeforeRouteLeave(() => canLeave()); onBeforeRouteUpdate(() => canLeave())
function beforeUnload(event: BeforeUnloadEvent) { if (dirty.value || saving.value) { event.preventDefault(); event.returnValue = '' } }
onMounted(() => window.addEventListener('beforeunload', beforeUnload)); onBeforeUnmount(() => { ++generation; window.removeEventListener('beforeunload', beforeUnload) })
async function save(continueAdding: boolean) {
  if (!canSave.value || !await formRef.value?.validate().catch(() => false)) return
  await checkDuplicates()
  if (!props.record && duplicates.value.length) { try { await ElMessageBox.confirm('请核对同名缺陷。确认不同问题后可以继续登记。', '同名缺陷提醒', { confirmButtonText: '仍然登记', cancelButtonText: '返回核对' }) } catch { return } }
  continuing.value = continueAdding; saving.value = true
  try {
    const payload: any = { ...form.value, title: form.value.title.trim(), description: form.value.description.trim(), reproduce_steps: form.value.reproduce_steps.filter(step => step.trim()).map(step => step.trim()), due_at: form.value.due_at?.toISOString() || null }
    for (const key of ['module_id', 'iteration_id', 'environment_profile_id', 'assignee_id', 'verifier_id']) payload[key] = payload[key] || null
    if (props.record) {
      delete payload.project_id
      if (!privileged.value) delete payload.priority
      if (!privileged.value || !['new', 'unassigned', 'reopened'].includes(props.record.workflow_state)) { delete payload.assignee_id; delete payload.verifier_id }
      payload.expected_version = props.record.row_version
    } else {
      delete payload.note
      payload.references = [...caseIds.value.map(id => ({ kind: 'case', case_asset_id: id })), ...(requirementId.value ? [{ kind: 'requirement', requirement_doc_id: requirementId.value, requirement_item_key: requirementKey.value || null }] : [])]
      const content = JSON.stringify(payload)
      if (lastPayload && lastPayload !== content) requestId.value = createRequestId()
      lastPayload = content; payload.creation_request_id = requestId.value
    }
    const response: any = props.record ? await defectsApi.update(props.record.id, payload) : await defectsApi.create(payload)
    baseline.value = serialized.value
    emit('saved', response.data, !props.record)
    ElMessage.success(props.record ? '缺陷已更新' : '缺陷已登记')
    if (continueAdding) {
      const previous = form.value; form.value = { ...blank(), project_id: previous.project_id, module_id: previous.module_id, environment_profile_id: previous.environment_profile_id }
      requirementId.value = ''; requirementKey.value = ''; caseIds.value = []; duplicates.value = []; lastPayload = ''; requestId.value = createRequestId(); baseline.value = serialized.value; formRef.value?.clearValidate()
    } else visible.value = false
  } catch (failure: any) {
    const detail = failure.response?.data?.detail
    submitError.value = typeof detail === 'string' ? detail : detail?.message || '保存失败，请核对输入后重试'
    versionConflict.value = !!props.record && failure.response?.status === 409
  } finally { saving.value = false }
}
async function reviewLatest() {
  if (!props.record) return
  try {
    const response: any = await defectsApi.get(props.record.id), latest: DefectRecord = response.data
    const changes = Object.keys(form.value).filter(key => defectFieldLabels[key] && JSON.stringify(latest[key]) !== JSON.stringify(props.record?.[key])).map(key => `${defectFieldLabels[key]}：${JSON.stringify(latest[key] ?? '未设置')}`).join('\n')
    await ElMessageBox.confirm(`此缺陷已更新至版本 ${latest.row_version}。\n${changes || '状态或其他关联信息发生了变化。'}\n\n继续将保留你的输入；请核对后再保存，保存会更新这些编辑字段。`, '核对最新修改', { confirmButtonText: '保留输入并重新核对', cancelButtonText: '继续比较', type: 'warning' })
    emit('rebase', latest); versionConflict.value = false; submitError.value = '已保留输入，请核对后重新保存。'
  } catch {}
}
</script>
<style scoped>
h3{margin:24px 0 14px;font-size:15px}.section-heading{display:flex;align-items:center;justify-content:space-between;gap:12px}.section-heading h3{margin:10px 0}.form-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:0 18px}.el-select{width:100%}.field-hint{font-size:12px;color:var(--el-text-color-secondary);margin-top:6px}.step-card{border:1px solid var(--el-border-color-light);padding:12px;border-radius:8px;margin:10px 0;background:var(--el-fill-color-lighter)}.step-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;font-size:13px}.form-alert{margin:14px 0}.drawer-footer{display:flex;justify-content:flex-end;gap:8px;flex-wrap:wrap}.drawer-footer .el-button{margin-left:0}a{color:var(--el-color-primary)}
@media(max-width:600px){.form-grid{grid-template-columns:1fr}.drawer-footer .el-button{flex:1}}
</style>
