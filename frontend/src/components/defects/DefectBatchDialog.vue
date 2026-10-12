<template>
  <el-dialog :model-value="modelValue" title="批量处理缺陷" width="640px" :close-on-click-modal="false" @update:model-value="emit('update:modelValue', $event)">
    <el-alert :title="`已选择 ${records.length} 条缺陷。系统会逐条校验权限、状态和版本，失败项不会影响其他成功项。`" type="info" :closable="false" />
    <el-form label-position="top" class="batch-form">
      <el-form-item label="操作"><el-select v-model="operation" @change="preview = undefined"><el-option label="指派责任人" value="assign"/><el-option label="调整优先级" value="priority"/><el-option label="调整模块" value="module"/><el-option label="调整迭代" value="iteration"/><el-option label="添加标签" value="add_labels"/><el-option label="移除标签" value="remove_labels"/><el-option label="批量流转" value="transition"/><el-option label="移入回收站" value="delete"/></el-select></el-form-item>
      <template v-if="operation === 'assign'"><el-form-item label="处理人"><el-select v-model="values.assignee_id" clearable filterable><el-option v-for="item in participants" :key="item.id" :label="item.username" :value="item.id"/></el-select></el-form-item><el-form-item label="验证人"><el-select v-model="values.verifier_id" clearable filterable><el-option v-for="item in participants" :key="item.id" :label="item.username" :value="item.id"/></el-select></el-form-item></template>
      <el-form-item v-if="operation === 'priority'" label="优先级"><el-select v-model="values.priority"><el-option v-for="(label, key) in defectPriorities" :key="key" :label="label" :value="key"/></el-select></el-form-item>
      <el-form-item v-if="operation === 'module'" label="所属模块"><el-select v-model="values.module_id" clearable><el-option v-for="item in metadata.modules" :key="item.id" :label="item.path" :value="item.id"/></el-select></el-form-item>
      <el-form-item v-if="operation === 'iteration'" label="所属迭代"><el-select v-model="values.iteration_id" clearable><el-option v-for="item in metadata.iterations" :key="item.id" :label="item.name" :value="item.id"/></el-select></el-form-item>
      <el-form-item v-if="['add_labels','remove_labels'].includes(operation)" label="标签"><el-select v-model="values.labels" multiple allow-create filterable default-first-option /></el-form-item>
      <el-form-item v-if="operation === 'transition'" label="流转动作"><el-select v-model="values.action_id"><el-option label="完成分诊" value="triage"/><el-option label="退回待分配" value="return_to_queue"/><el-option label="关闭" value="close"/><el-option label="重开" value="reopen"/></el-select></el-form-item>
      <el-form-item v-if="operation !== 'delete'" label="操作说明"><el-input v-model="values.note" type="textarea" :rows="2" maxlength="5000"/></el-form-item>
    </el-form>
    <el-alert v-if="preview" :title="`预检：可执行 ${preview.summary.success} 条，失败 ${preview.summary.failed} 条`" :type="preview.summary.failed ? 'warning' : 'success'" :closable="false" />
    <el-table v-if="preview?.failed?.length" :data="preview.failed" size="small" max-height="180"><el-table-column prop="defect_key" label="缺陷" width="120"/><el-table-column prop="message" label="失败原因"/></el-table>
    <template #footer><el-button @click="emit('update:modelValue', false)">取消</el-button><el-button :loading="previewing" @click="runPreview">预检</el-button><el-button type="primary" :disabled="!preview?.succeeded?.length" :loading="executing" @click="execute">执行可通过项</el-button></template>
  </el-dialog>
</template>
<script setup lang="ts">
import { reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { defectsApi } from '@/api'
import { defectPriorities } from '@/types/defects'
const props = defineProps<{ modelValue: boolean; projectId: string; records: any[]; participants: any[]; metadata: any }>()
const emit = defineEmits<{ 'update:modelValue': [boolean]; completed: [] }>()
const operation = ref('assign'), values = reactive<any>({}), preview = ref<any>(), previewing = ref(false), executing = ref(false)
watch(() => props.modelValue, value => { if (value) { operation.value = 'assign'; for (const key of Object.keys(values)) delete values[key]; preview.value = undefined } })
function payload(isPreview: boolean) { return { project_id: props.projectId, defect_ids: props.records.map(item => item.id), operation: operation.value, values: { ...values, ...(isPreview ? {} : { expected_versions: Object.fromEntries(preview.value.succeeded.map((item: any) => [item.id, item.row_version])) }) }, preview: isPreview } }
async function runPreview() { previewing.value = true; try { const res: any = await defectsApi.batch(payload(true)); preview.value = res.data } finally { previewing.value = false } }
async function execute() { await ElMessageBox.confirm(`将对 ${preview.value.succeeded.length} 条缺陷执行批量操作，确定继续？`, '确认批量操作', { type: operation.value === 'delete' ? 'warning' : 'info' }); executing.value = true; try { const res: any = await defectsApi.batch(payload(false)); preview.value = res.data; ElMessage.success(`批量处理完成：成功 ${res.data.summary.success}，失败 ${res.data.summary.failed}`); emit('completed'); if (!res.data.summary.failed) emit('update:modelValue', false) } finally { executing.value = false } }
</script>
<style scoped>.batch-form{margin-top:16px}.batch-form .el-select{width:100%}</style>
