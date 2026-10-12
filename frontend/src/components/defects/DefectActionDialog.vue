<template>
  <el-dialog :model-value="modelValue" :title="action?.label || '指派责任人'" width="580px" :close-on-click-modal="false" :before-close="beforeClose" class="defect-action-dialog" @update:model-value="emit('update:modelValue', $event)">
    <el-alert :title="`${record.defect_key} · ${record.title}`" type="info" :closable="false" class="action-intro" />
    <el-form label-position="top" v-loading="loading" @submit.prevent="submit">
      <el-form-item v-if="isAssign || ['start', 'resume'].includes(actionId)" label="处理人" :required="!isAssign"><el-select v-model="form.assignee_id" filterable :clearable="isAssign && !['in_progress', 'pending_verification'].includes(record.workflow_state)" aria-label="流转处理人"><el-option v-for="item in assignees" :key="item.id" :label="item.username" :value="item.id" /></el-select></el-form-item>
      <el-form-item v-if="isAssign || actionId === 'submit_fix'" label="验证人" :required="actionId === 'submit_fix'"><el-select v-model="form.verifier_id" filterable :clearable="isAssign && record.workflow_state !== 'pending_verification'" aria-label="流转验证人"><el-option v-for="item in verifiers" :key="item.id" :label="item.username" :value="item.id" /></el-select></el-form-item>
      <template v-if="actionId === 'submit_fix'">
        <el-form-item label="修复版本"><el-select v-model="form.fix_release_id" clearable filterable aria-label="修复版本"><el-option v-for="item in releases" :key="item.id" :label="item.name" :value="item.id" /></el-select></el-form-item>
        <el-form-item label="修复构建号"><el-input v-model="form.fix_build" aria-label="修复构建号" maxlength="200" placeholder="版本与构建号至少填写一项" /></el-form-item>
        <el-form-item><el-checkbox v-model="form.fix_available">确认修复已在被测环境中可验证</el-checkbox></el-form-item>
      </template>
      <template v-if="actionId === 'verify_pass'">
        <el-form-item label="验证版本"><el-select v-model="form.verified_release_id" clearable filterable aria-label="验证版本"><el-option v-for="item in releases" :key="item.id" :label="item.name" :value="item.id" /></el-select></el-form-item>
        <el-form-item label="验证构建号"><el-input v-model="form.verified_build" aria-label="验证构建号" maxlength="200" placeholder="填写实际验证的版本或构建号" /></el-form-item>
      </template>
      <el-form-item v-if="actionId === 'verify_fail'" label="验证实际结果" required><el-input v-model="form.actual_result" aria-label="验证实际结果" type="textarea" :rows="3" maxlength="10000" /></el-form-item>
      <template v-if="actionId === 'reject'">
        <el-form-item label="拒绝结果" required><el-select v-model="form.resolution" aria-label="拒绝结果"><el-option label="重复缺陷" value="duplicate" /><el-option label="不是缺陷" value="not_a_bug" /><el-option label="决定不修复" value="wont_fix" /><el-option label="无法复现" value="cannot_reproduce" /></el-select></el-form-item>
        <el-form-item v-if="form.resolution === 'duplicate'" label="主缺陷" required><el-select v-model="form.duplicate_of_id" filterable remote :remote-method="searchDuplicates" aria-label="主缺陷" placeholder="搜索同项目缺陷"><el-option v-for="item in duplicateOptions" :key="item.id" :label="`${item.defect_key} · ${item.title}`" :value="item.id" /></el-select></el-form-item>
      </template>
      <el-form-item :label="actionId === 'submit_fix' ? '修复说明' : actionId.startsWith('verify') ? '验证说明' : '操作说明'" :required="noteRequired"><el-input v-model="form.note" aria-label="操作说明" type="textarea" :rows="3" maxlength="5000" placeholder="说明修复、验证结果或本次操作原因" /></el-form-item>
      <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon><el-button v-if="conflict" link type="primary" @click="emit('refresh')">刷新缺陷后重新核对</el-button></el-alert>
    </el-form>
    <template #footer><el-button :disabled="saving" @click="close">取消</el-button><el-button type="primary" :loading="saving" :disabled="loading" @click="submit">确认{{ isAssign ? '指派' : action?.label }}</el-button></template>
  </el-dialog>
</template>
<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { onBeforeRouteLeave, onBeforeRouteUpdate } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { defectsApi } from '@/api'
import { useAuthStore } from '@/stores'
import { createRequestId } from '@/utils/requestId'
import type { DefectAction, DefectRecord } from '@/types/defects'
const props = defineProps<{ modelValue: boolean; record: DefectRecord; action?: DefectAction | null }>()
const emit = defineEmits(['update:modelValue', 'saved', 'refresh'])
const auth = useAuthStore(), isAssign = computed(() => !props.action), actionId = computed(() => props.action?.action_id || 'assign')
const form = ref<any>({}), assignees = ref<any[]>([]), verifiers = ref<any[]>([]), releases = ref<any[]>([]), duplicateOptions = ref<any[]>([])
const loading = ref(false), saving = ref(false), error = ref(''), conflict = ref(false)
const baseline = ref(''); let requestId = createRequestId(), previousPayload = '', generation = 0
const noteRequired = computed(() => props.action?.required_fields.includes('note') || (isAssign.value && ['in_progress', 'pending_verification'].includes(props.record.workflow_state)) || (['start', 'resume', 'submit_fix'].includes(actionId.value) && props.record.assignee_id !== auth.user?.id) || (['verify_pass', 'verify_fail'].includes(actionId.value) && props.record.verifier_id !== auth.user?.id))
watch(() => props.modelValue, async value => {
  if (!value) { ++generation; return }
  form.value = { assignee_id: props.record.assignee_id || '', verifier_id: props.record.verifier_id || '', fix_release_id: '', fix_build: '', verified_release_id: '', verified_build: '', actual_result: '', resolution: '', duplicate_of_id: '', fix_available: false, note: '' }
  baseline.value = JSON.stringify(form.value); error.value = ''; conflict.value = false; requestId = createRequestId(); previousPayload = ''
  const stamp = ++generation; loading.value = true
  try {
    const [developers, testers, meta]: any = await Promise.all([defectsApi.participants(props.record.project_id, 'assignee'), defectsApi.participants(props.record.project_id, 'verifier'), defectsApi.metadata(props.record.project_id)])
    if (stamp !== generation) return
    assignees.value = developers.data.items; verifiers.value = testers.data.items; releases.value = meta.data.releases; await searchDuplicates('')
  } catch { error.value = '选项加载失败，请关闭后重试' } finally { if (stamp === generation) loading.value = false }
})
async function canClose() {
  if (!props.modelValue) return true
  if (saving.value) return false
  if (JSON.stringify(form.value) === baseline.value) return true
  try { await ElMessageBox.confirm('流转内容尚未提交，关闭将丢失当前输入。', '放弃未提交内容？', { confirmButtonText: '放弃并关闭', cancelButtonText: '继续编辑' }); return true } catch { return false }
}
onBeforeRouteLeave(() => canClose()); onBeforeRouteUpdate(() => canClose())
function beforeUnload(event: BeforeUnloadEvent) { if (props.modelValue && (saving.value || JSON.stringify(form.value) !== baseline.value)) { event.preventDefault(); event.returnValue = '' } }
onMounted(() => window.addEventListener('beforeunload', beforeUnload)); onBeforeUnmount(() => { ++generation; window.removeEventListener('beforeunload', beforeUnload) })
async function beforeClose(done: () => void) { if (await canClose()) done() }
async function close() { if (await canClose()) emit('update:modelValue', false) }
async function searchDuplicates(q: string) {
  if (actionId.value !== 'reject') return
  try { const response: any = await defectsApi.list({ project_id: props.record.project_id, q, page_size: 20 }); duplicateOptions.value = response.data.list.filter((item: any) => item.id !== props.record.id) } catch {}
}
async function submit() {
  if (saving.value || loading.value) return
  error.value = ''; conflict.value = false
  if (noteRequired.value && !form.value.note.trim()) { error.value = '请填写本次操作说明'; return }
  const fields: any = {}
  if (isAssign.value) { fields.assignee_id = form.value.assignee_id || null; fields.verifier_id = form.value.verifier_id || null }
  if (['start', 'resume'].includes(actionId.value) && !props.record.assignee_id) fields.assignee_id = form.value.assignee_id || null
  if (actionId.value === 'submit_fix') {
    if (!form.value.verifier_id || (!form.value.fix_release_id && !form.value.fix_build.trim()) || !form.value.fix_available) { error.value = '请选择验证人、填写修复版本或构建号，并确认修复可验证'; return }
    Object.assign(fields, { verifier_id: form.value.verifier_id, fix_release_id: form.value.fix_release_id || null, fix_build: form.value.fix_build.trim() || null, fix_available: true })
  }
  if (actionId.value === 'verify_pass') {
    if (!form.value.verified_release_id && !form.value.verified_build.trim()) { error.value = '请填写实际验证的版本或构建号'; return }
    Object.assign(fields, { verified_release_id: form.value.verified_release_id || null, verified_build: form.value.verified_build.trim() || null })
  }
  if (actionId.value === 'verify_fail') { if (!form.value.actual_result.trim()) { error.value = '请填写验证实际结果'; return }; fields.actual_result = form.value.actual_result.trim() }
  if (actionId.value === 'reject') {
    if (!form.value.resolution || (form.value.resolution === 'duplicate' && !form.value.duplicate_of_id)) { error.value = '请填写拒绝结果，重复缺陷需指定主缺陷'; return }
    fields.resolution = form.value.resolution; if (fields.resolution === 'duplicate') fields.duplicate_of_id = form.value.duplicate_of_id
  }
  const payload: any = { expected_version: props.record.row_version, note: form.value.note.trim(), ...(isAssign.value ? fields : { action_id: actionId.value, fields }) }
  const digest = JSON.stringify(payload)
  if (previousPayload && previousPayload !== digest) requestId = createRequestId()
  previousPayload = digest; payload.request_id = requestId; saving.value = true
  try {
    const response: any = isAssign.value ? await defectsApi.assign(props.record.id, payload) : await defectsApi.transition(props.record.id, payload)
    baseline.value = JSON.stringify(form.value); ElMessage.success(isAssign.value ? '责任人已更新' : '缺陷流转成功'); emit('saved', response.data.detail); emit('update:modelValue', false)
  } catch (failure: any) {
    const detail = failure.response?.data?.detail; error.value = typeof detail === 'string' ? detail : detail?.message || '提交失败，请核对后重试'; conflict.value = failure.response?.status === 409
  } finally { saving.value = false }
}
</script>
<style scoped>
.action-intro{margin-bottom:20px}.el-select{width:100%}@media(max-width:620px){:global(.defect-action-dialog){width:calc(100vw - 24px)!important}}
</style>
