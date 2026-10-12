<template>
  <el-drawer
    v-model="visible"
    title="手动添加用例"
    size="min(780px, 96vw)"
    class="manual-case-drawer"
    :close-on-click-modal="false"
    :before-close="beforeClose"
    destroy-on-close
  >
    <div class="form-intro">{{ projectName }} · 保存后进入草稿，可在用例库继续编辑和提交评审。</div>
    <el-alert v-if="optionsFailed" title="目录、标签和需求加载失败，可重试后继续录入。" type="warning" :closable="false" show-icon>
      <el-button text type="primary" @click="loadOptions">重新加载</el-button>
    </el-alert>
    <el-form ref="formRef" :model="form" :rules="rules" label-position="top" :disabled="saving" class="manual-form" @submit.prevent>
      <el-form-item label="用例标题" prop="title">
        <el-input v-model="form.title" placeholder="例如：未登录用户无法提交订单" maxlength="500" show-word-limit autofocus />
      </el-form-item>
      <div class="form-grid">
        <el-form-item label="所属模块 / 目录" prop="folder">
          <el-select v-model="form.folder" filterable allow-create default-first-option clearable placeholder="选择或输入目录" :loading="optionsLoading">
            <el-option v-for="folder in options.folders" :key="folder" :label="folder" :value="folder" />
          </el-select>
        </el-form-item>
        <el-form-item label="优先级" prop="priority">
          <el-select v-model="form.priority"><el-option v-for="priority in ['P0', 'P1', 'P2', 'P3']" :key="priority" :label="priority" :value="priority" /></el-select>
        </el-form-item>
        <el-form-item label="用例类型" prop="case_type">
          <el-select v-model="form.case_type"><el-option v-for="type in MANUAL_CASE_TYPES" :key="type.value" :label="type.label" :value="type.value" /></el-select>
        </el-form-item>
        <el-form-item label="标签" prop="tags">
          <el-select v-model="form.tags" multiple filterable allow-create default-first-option :multiple-limit="20" placeholder="输入标签后回车" :loading="optionsLoading">
            <el-option v-for="tag in options.tags" :key="tag" :label="tag" :value="tag" />
          </el-select>
        </el-form-item>
      </div>
      <el-form-item label="用例说明"><el-input v-model="form.description" type="textarea" :rows="2" maxlength="10000" placeholder="补充业务场景或测试目的（选填）" /></el-form-item>
      <div class="form-grid">
        <el-form-item label="关联需求文档">
          <el-select v-model="form.requirement_doc_id" clearable filterable placeholder="选择当前项目的需求文档（选填）" :loading="optionsLoading">
            <el-option v-for="doc in options.requirements" :key="doc.id" :label="doc.filename" :value="doc.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="需求编号 / 链接">
          <el-input v-model="form.requirement_ref" maxlength="500" placeholder="例如：REQ-102 或需求链接（选填）" />
        </el-form-item>
      </div>
      <el-form-item label="前置条件"><el-input v-model="form.preconditions" type="textarea" :rows="3" maxlength="10000" placeholder="例如：测试账号已注册、购物车中有商品（选填）" /></el-form-item>
      <div class="steps-heading"><strong>操作步骤 <span class="required-mark">*</span></strong><span>按执行顺序填写，可上下移动调整</span></div>
      <div v-for="(step, index) in form.steps" :key="step.id" class="step-card">
        <div class="step-heading">
          <span>步骤 {{ index + 1 }}</span>
          <div>
            <el-button text :icon="ArrowUp" :disabled="index === 0" :aria-label="`上移步骤 ${index + 1}`" :title="`上移步骤 ${index + 1}`" @click="moveStep(index, -1)" />
            <el-button text :icon="ArrowDown" :disabled="index === form.steps.length - 1" :aria-label="`下移步骤 ${index + 1}`" :title="`下移步骤 ${index + 1}`" @click="moveStep(index, 1)" />
            <el-button text type="danger" :icon="Delete" :disabled="form.steps.length === 1" :aria-label="`删除步骤 ${index + 1}`" :title="`删除步骤 ${index + 1}`" @click="removeStep(index)" />
          </div>
        </div>
        <el-form-item :prop="`steps.${index}.text`" :rules="stepRules">
          <el-input v-model="step.text" type="textarea" :rows="2" maxlength="5000" :aria-label="`步骤 ${index + 1} 操作内容`" placeholder="填写具体操作，例如：点击「提交订单」按钮" />
        </el-form-item>
      </div>
      <el-button plain :icon="Plus" :disabled="form.steps.length >= 100" @click="addStep">添加步骤</el-button>
      <el-form-item label="预期结果" prop="expected_result" class="expected-field">
        <el-input v-model="form.expected_result" type="textarea" :rows="4" maxlength="10000" placeholder="填写可验证的结果，例如：跳转登录页，订单未被创建" />
      </el-form-item>
    </el-form>
    <el-alert v-if="duplicates.length" title="当前项目已有同名用例，请核对内容后再保存" type="warning" :closable="false" show-icon class="duplicate-alert">
      <ul><li v-for="item in duplicates" :key="item.id">{{ item.title }} · {{ item.folder }}</li></ul>
      <span>再次保存会询问是否继续添加，已有用例不会被覆盖。</span>
    </el-alert>
    <template #footer>
      <div class="drawer-footer">
        <el-button :disabled="saving" @click="beforeClose(() => visible = false)">取消</el-button>
        <el-button :disabled="saving" :loading="saving && saveIntent === 'continue'" @click="save(true)">保存并继续添加</el-button>
        <el-button type="primary" :disabled="saving" :loading="saving && saveIntent === 'close'" @click="save(false)">保存用例</el-button>
      </div>
    </template>
  </el-drawer>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { onBeforeRouteLeave, onBeforeRouteUpdate } from 'vue-router'
import { ElMessage, ElMessageBox, type FormInstance, type FormItemRule, type FormRules } from 'element-plus'
import { ArrowDown, ArrowUp, Delete, Plus } from '@element-plus/icons-vue'
import { caseApi } from '@/api'
import { MANUAL_CASE_TYPES, type CreateManualCasePayload, type ManualCaseOptions } from '@/types/manualCase'

const props = defineProps<{ modelValue: boolean; projectId: string; projectName: string }>()
const emit = defineEmits<{ (event: 'update:modelValue', value: boolean): void; (event: 'saved', asset: any): void }>()
const visible = computed({ get: () => props.modelValue, set: value => emit('update:modelValue', value) })
let nextStepId = 0
function newStep() { return { id: ++nextStepId, text: '' } }
function emptyForm() {
  return { title: '', description: '', folder: '', priority: 'P2' as CreateManualCasePayload['priority'], case_type: 'functional' as CreateManualCasePayload['case_type'], tags: [] as string[], requirement_doc_id: '' as string, requirement_ref: '', preconditions: '', steps: [newStep()], expected_result: '' }
}
const form = ref(emptyForm())
const formRef = ref<FormInstance>()
const baseline = ref('')
const saving = ref(false)
const saveIntent = ref<'close' | 'continue'>('close')
const duplicates = ref<Array<{ id: string; title: string; folder: string }>>([])
const duplicateTitle = ref('')
const options = ref<ManualCaseOptions>({ folders: [], tags: [], requirements: [] })
const optionsLoading = ref(false)
const optionsFailed = ref(false)
const serialized = computed(() => JSON.stringify({ ...form.value, steps: form.value.steps.map(step => step.text) }))
const dirty = computed(() => visible.value && serialized.value !== baseline.value)
const requiredText: FormItemRule = { required: true, validator: (_rule, value, callback) => callback(typeof value === 'string' && value.trim() ? undefined : new Error('请填写内容，不能只输入空格')), trigger: 'blur' }
const stepRules: FormItemRule[] = [requiredText]
const rules: FormRules = {
  title: [requiredText], expected_result: [requiredText],
  folder: [{ max: 200, message: '目录不能超过 200 个字符', trigger: 'change' }],
  tags: [{ validator: (_rule, value: string[], callback) => callback(value.some(tag => tag.trim().length > 40) ? new Error('单个标签不能超过 40 个字符') : undefined), trigger: 'change' }],
}

async function loadOptions() {
  optionsLoading.value = true; optionsFailed.value = false
  try { const response: any = await caseApi.manualOptions(props.projectId); options.value = response.data }
  catch { optionsFailed.value = true }
  finally { optionsLoading.value = false }
}
function resetForm(keepContext = false) {
  const previous = form.value
  form.value = emptyForm()
  if (keepContext) Object.assign(form.value, { folder: previous.folder, priority: previous.priority, case_type: previous.case_type, tags: [...previous.tags], requirement_doc_id: previous.requirement_doc_id, requirement_ref: previous.requirement_ref })
  baseline.value = serialized.value; duplicates.value = []; duplicateTitle.value = ''
  nextTick(() => formRef.value?.clearValidate())
}
watch(visible, value => { if (value) { resetForm(); loadOptions() } })
watch(() => form.value.title, value => { if (value.trim() !== duplicateTitle.value) duplicates.value = [] })
function addStep() { form.value.steps.push(newStep()) }
function removeStep(index: number) { formRef.value?.clearValidate(); form.value.steps.splice(index, 1) }
function moveStep(index: number, direction: number) {
  const target = index + direction
  if (target < 0 || target >= form.value.steps.length) return
  formRef.value?.clearValidate()
  const step = form.value.steps.splice(index, 1)[0]; form.value.steps.splice(target, 0, step)
}
let discardPrompt: Promise<boolean> | undefined
async function canLeave(): Promise<boolean> {
  if (saving.value) { ElMessage.warning('正在保存，请稍候'); return false }
  if (!dirty.value) return true
  if (!discardPrompt) discardPrompt = ElMessageBox.confirm('当前用例尚未保存，离开将丢失已填写的内容。', '放弃未保存内容？', { type: 'warning', confirmButtonText: '放弃并离开', cancelButtonText: '继续编辑', distinguishCancelAndClose: true }).then(() => true, () => false).finally(() => { discardPrompt = undefined })
  return discardPrompt
}
async function beforeClose(done: () => void) { if (await canLeave()) done() }
onBeforeRouteLeave(() => canLeave())
onBeforeRouteUpdate(() => canLeave())
function onBeforeUnload(event: BeforeUnloadEvent) { if (dirty.value || saving.value) { event.preventDefault(); event.returnValue = '' } }
onMounted(() => window.addEventListener('beforeunload', onBeforeUnload))
onBeforeUnmount(() => window.removeEventListener('beforeunload', onBeforeUnload))

async function confirmDuplicate(): Promise<boolean> {
  try { await ElMessageBox.confirm('已存在同名用例。请确认这是需要单独保存的新场景，继续后将新建一条草稿。', '确认添加同名用例', { type: 'warning', confirmButtonText: '仍然添加', cancelButtonText: '返回修改' }); return true }
  catch { return false }
}
async function save(continueAdding: boolean) {
  if (saving.value || !await formRef.value?.validate().catch(() => false)) return
  saveIntent.value = continueAdding ? 'continue' : 'close'
  saving.value = true
  try {
    const payload: CreateManualCasePayload = { ...form.value, project_id: props.projectId, title: form.value.title.trim(), steps: form.value.steps.map(step => step.text.trim()), expected_result: form.value.expected_result.trim(), requirement_doc_id: form.value.requirement_doc_id || null }
    if (duplicates.value.length) { if (!await confirmDuplicate()) return; payload.allow_duplicate = true }
    let response: any
    try { response = await caseApi.createManual(payload) }
    catch (error: any) {
      const detail = error.response?.data?.detail
      if (error.response?.status === 409 && detail?.code === 'CASE_DUPLICATE') {
        duplicates.value = detail.duplicates || []; duplicateTitle.value = payload.title
        ElMessage.warning('发现同名用例，请核对表单底部的提醒后再次保存')
      }
      return
    }
    baseline.value = serialized.value
    emit('saved', response.data)
    ElMessage.success(continueAdding ? '用例已保存，目录和标签已保留，可继续添加下一条' : '用例已保存为草稿，已定位到列表')
    if (continueAdding) {
      if (payload.folder && !options.value.folders.includes(payload.folder)) options.value.folders.push(payload.folder)
      options.value.tags = Array.from(new Set([...options.value.tags, ...payload.tags]))
      resetForm(true)
      await nextTick(); formRef.value?.$el.querySelector('input')?.focus()
    } else visible.value = false
  } finally { saving.value = false }
}
</script>

<style scoped>
.form-intro { margin-bottom: 20px; color: var(--el-text-color-secondary); font-size: 13px; line-height: 1.7; }
.manual-form { margin-top: 14px; }.form-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 16px; }.el-select { width: 100%; }
.steps-heading, .step-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; }.steps-heading { margin: 8px 0 12px; }.steps-heading > span { color: var(--el-text-color-secondary); font-size: 12px; }.required-mark { color: var(--el-color-danger); }
.step-card { margin-bottom: 12px; padding: 12px; border: 1px solid var(--el-border-color-light); border-radius: var(--el-border-radius-base); background: var(--el-fill-color-lighter); }.step-heading { margin-bottom: 8px; font-size: 13px; font-weight: 600; }.step-heading .el-button + .el-button { margin-left: 2px; }.step-card .el-form-item { margin-bottom: 0; padding-bottom: 16px; }
.expected-field { margin-top: 22px; }.duplicate-alert { margin-top: 16px; }.duplicate-alert ul { padding-left: 18px; }.drawer-footer { display: flex; justify-content: flex-end; gap: 8px; flex-wrap: wrap; }.drawer-footer .el-button { margin-left: 0; }
@media (max-width: 600px) { .form-grid { grid-template-columns: 1fr; }.steps-heading { align-items: flex-start; flex-direction: column; gap: 4px; }.drawer-footer { justify-content: stretch; }.drawer-footer .el-button { flex: 1; } }
</style>
