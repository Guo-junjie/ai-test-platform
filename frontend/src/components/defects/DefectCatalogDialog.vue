<template>
  <el-dialog :model-value="modelValue" title="项目缺陷目录" width="640px" class="defect-catalog" :close-on-click-modal="false" @update:model-value="emit('update:modelValue', $event)">
    <el-alert title="目录属于当前项目，停用后不影响已有缺陷记录。" type="info" :closable="false" />
    <el-tabs v-model="kind" @tab-change="reset">
      <el-tab-pane label="模块" name="modules" /><el-tab-pane label="迭代" name="iterations" /><el-tab-pane label="版本" name="releases" />
    </el-tabs>
    <el-form label-position="top" @submit.prevent="save">
      <el-form-item :label="`${kindLabel}名称`" required><el-input v-model="form.name" :aria-label="`${kindLabel}名称`" maxlength="100" placeholder="输入名称" /></el-form-item>
      <el-form-item v-if="kind === 'modules'" label="父模块"><el-select v-model="form.parent_id" clearable filterable placeholder="根目录" aria-label="父模块"><el-option v-for="item in items.filter(item => item.is_active)" :key="item.id" :value="item.id" :label="item.path" /></el-select></el-form-item>
      <template v-if="kind === 'iterations'"><el-form-item label="迭代时间"><el-date-picker v-model="dates" type="datetimerange" start-placeholder="开始时间" end-placeholder="结束时间" /></el-form-item></template>
      <el-form-item v-if="kind === 'releases'" label="构建号"><el-input v-model="form.build_ref" aria-label="构建号" maxlength="200" placeholder="例如 orders-20261009.3" /></el-form-item>
      <el-button type="primary" :icon="Plus" :loading="saving" @click="save">添加{{ kindLabel }}</el-button>
    </el-form>
    <el-table :data="items" class="catalog-table" max-height="260" empty-text="暂无目录，请先添加">
      <el-table-column label="名称" min-width="180"><template #default="{ row }">{{ row.path || row.name }}</template></el-table-column>
      <el-table-column label="状态" width="90"><template #default="{ row }">{{ (row.is_active === false || row.status === 'archived') ? '已停用' : '可用' }}</template></el-table-column>
      <el-table-column label="操作" width="85"><template #default="{ row }"><el-button link :disabled="saving" @click="toggle(row)">{{ (row.is_active === false || row.status === 'archived') ? '启用' : '停用' }}</el-button></template></el-table-column>
    </el-table>
    <template #footer><el-button @click="emit('update:modelValue', false)">完成</el-button></template>
  </el-dialog>
</template>
<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Plus } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { defectsApi } from '@/api'
const props = defineProps<{ modelValue: boolean; projectId: string }>()
const emit = defineEmits(['update:modelValue', 'changed'])
const kind = ref('modules'), items = ref<any[]>([]), saving = ref(false)
const kindLabel = computed(() => ({ modules: '模块', iterations: '迭代', releases: '版本' }[kind.value] || '目录'))
const form = ref({ name: '', parent_id: '', build_ref: '' }), dates = ref<Date[] | null>(null)
async function load() { const response: any = await defectsApi.catalogList(props.projectId, kind.value); items.value = response.data.items }
function reset() { form.value = { name: '', parent_id: '', build_ref: '' }; dates.value = null; void load().catch(() => {}) }
watch(() => props.modelValue, value => { if (value) reset() })
async function save() {
  if (saving.value || !form.value.name.trim()) { if (!form.value.name.trim()) ElMessage.warning('请填写目录名称'); return }
  saving.value = true
  try {
    const payload: any = { name: form.value.name.trim() }
    if (kind.value === 'modules') payload.parent_id = form.value.parent_id || null
    if (kind.value === 'releases') payload.build_ref = form.value.build_ref || null
    if (kind.value === 'iterations' && dates.value) { payload.start_date = dates.value[0].toISOString(); payload.end_date = dates.value[1].toISOString() }
    await defectsApi.catalogCreate(props.projectId, kind.value, payload)
    ElMessage.success('目录已添加'); reset(); emit('changed')
  } catch { /* API 拦截器显示错误 */ } finally { saving.value = false }
}
async function toggle(row: any) {
  saving.value = true
  try {
    const payload: any = { name: row.name }
    if (kind.value === 'modules') { payload.parent_id = row.parent_id; payload.is_active = !row.is_active }
    else payload.status = row.status === 'archived' ? 'planned' : 'archived'
    await defectsApi.catalogUpdate(props.projectId, kind.value, row.id, payload); await load(); emit('changed')
  } catch {} finally { saving.value = false }
}
</script>
<style scoped>
.el-select{width:100%}.catalog-table{margin-top:20px}:deep(.el-date-editor){max-width:100%}
@media(max-width:680px){:global(.defect-catalog){width:calc(100vw - 24px)!important}}
</style>
