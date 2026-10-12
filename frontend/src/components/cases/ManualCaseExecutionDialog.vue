<template>
  <el-dialog :model-value="modelValue" title="手工执行" width="860px" destroy-on-close @update:model-value="emit('update:modelValue', $event)" @open="loadHistory">
    <el-alert type="info" :closable="false" show-icon title="执行记录绑定当前不可变用例版本；提交后不可修改，可再次执行形成新的记录。" />
    <div class="case-heading"><b>{{ caseItem?.title }}</b><el-tag size="small">v{{ caseItem?.version }}</el-tag></div>

    <template v-if="activeExecution">
      <el-descriptions :column="3" border size="small">
        <el-descriptions-item label="执行版本">v{{ activeExecution.case_version }}</el-descriptions-item>
        <el-descriptions-item label="开始时间">{{ formatTime(activeExecution.started_at) }}</el-descriptions-item>
        <el-descriptions-item label="状态"><el-tag type="warning">执行中</el-tag></el-descriptions-item>
      </el-descriptions>
      <div class="section-title">逐步执行</div>
      <div v-for="(step, index) in activeExecution.step_results" :key="step.index" class="step-card">
        <div class="step-title"><span class="step-index">{{ index + 1 }}</span><span>{{ step.step }}</span></div>
        <div class="step-result">
          <el-select v-model="step.status" placeholder="选择结果">
            <el-option label="通过" value="passed" /><el-option label="失败" value="failed" />
            <el-option label="阻塞" value="blocked" /><el-option label="跳过" value="skipped" />
          </el-select>
          <el-input v-model="step.actual" placeholder="填写该步骤的实际结果或证据说明" />
        </div>
      </div>
      <el-form label-position="top" class="conclusion-form">
        <el-form-item label="执行结论" required><el-radio-group v-model="conclusion"><el-radio-button value="passed">通过</el-radio-button><el-radio-button value="failed">失败</el-radio-button><el-radio-button value="blocked">阻塞</el-radio-button><el-radio-button value="cancelled">取消</el-radio-button></el-radio-group></el-form-item>
        <el-form-item label="实际结果" :required="['failed', 'blocked'].includes(conclusion)"><el-input v-model="actualResult" type="textarea" :rows="3" placeholder="说明实际表现、失败现象或阻塞原因" /></el-form-item>
        <el-form-item label="执行备注"><el-input v-model="notes" type="textarea" :rows="2" /></el-form-item>
      </el-form>
    </template>
    <el-empty v-else description="尚未开始本次执行"><el-button type="primary" :loading="starting" @click="startExecution">开始执行当前版本</el-button></el-empty>

    <div class="section-header"><div class="section-title">执行历史</div><el-button text @click="loadHistory">刷新</el-button></div>
    <el-table :data="history" v-loading="loading" size="small" border empty-text="暂无执行记录">
      <el-table-column label="结果" width="90"><template #default="{ row }"><el-tag :type="statusType(row.status)">{{ statusLabel(row.status) }}</el-tag></template></el-table-column>
      <el-table-column label="版本" width="75"><template #default="{ row }">v{{ row.case_version }}</template></el-table-column>
      <el-table-column prop="executor_name" label="执行人" width="120" />
      <el-table-column prop="actual_result" label="实际结果" min-width="220" show-overflow-tooltip />
      <el-table-column label="完成时间" width="170"><template #default="{ row }">{{ formatTime(row.completed_at || row.started_at) }}</template></el-table-column>
    </el-table>

    <template #footer>
      <el-button @click="emit('update:modelValue', false)">关闭</el-button>
      <el-button v-if="activeExecution" type="primary" :loading="submitting" @click="submitResult">提交执行结果</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { caseApi } from '@/api'

const props = defineProps<{ modelValue: boolean; caseItem: any }>()
const emit = defineEmits<{ (event: 'update:modelValue', value: boolean): void; (event: 'completed'): void }>()
const history = ref<any[]>([])
const activeExecution = ref<any>()
const loading = ref(false), starting = ref(false), submitting = ref(false)
const conclusion = ref('passed'), actualResult = ref(''), notes = ref('')

function formatTime(value?: string) { return value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '—' }
function statusLabel(value: string) { return ({ in_progress: '执行中', passed: '通过', failed: '失败', blocked: '阻塞', cancelled: '取消' } as any)[value] || value }
function statusType(value: string): any { return value === 'passed' ? 'success' : value === 'failed' ? 'danger' : value === 'in_progress' ? 'warning' : 'info' }

async function loadHistory() {
  if (!props.caseItem?.id) return
  loading.value = true
  try {
    const response: any = await caseApi.manualExecutions(props.caseItem.id)
    history.value = response?.data || []
    activeExecution.value = history.value.find(item => item.status === 'in_progress')
  } finally { loading.value = false }
}
async function startExecution() {
  starting.value = true
  try {
    const response: any = await caseApi.startManualExecution(props.caseItem.id)
    activeExecution.value = response?.data
    conclusion.value = 'passed'; actualResult.value = ''; notes.value = ''
    await loadHistory()
  } finally { starting.value = false }
}
async function submitResult() {
  const steps = activeExecution.value?.step_results || []
  if (steps.some((item: any) => item.status === 'pending')) return ElMessage.warning('请为每个步骤选择执行结果')
  if (conclusion.value === 'passed' && steps.some((item: any) => item.status !== 'passed')) return ElMessage.warning('存在未通过步骤，执行结论不能选择通过')
  if (['failed', 'blocked'].includes(conclusion.value) && !actualResult.value.trim()) return ElMessage.warning('失败或阻塞时请填写实际结果')
  submitting.value = true
  try {
    await caseApi.completeManualExecution(props.caseItem.id, activeExecution.value.id, {
      status: conclusion.value, step_results: steps, actual_result: actualResult.value, notes: notes.value,
    })
    ElMessage.success('手工执行结果已提交')
    activeExecution.value = undefined
    await loadHistory()
    emit('completed')
  } finally { submitting.value = false }
}
</script>

<style scoped>
.case-heading,.section-header,.step-title,.step-result{display:flex;align-items:center;gap:10px}.case-heading{margin:16px 0}.section-title{margin:18px 0 10px;font-weight:600}.section-header{justify-content:space-between}.step-card{padding:12px;margin-bottom:10px;border:1px solid var(--el-border-color);border-radius:8px}.step-title{align-items:flex-start}.step-index{display:inline-flex;align-items:center;justify-content:center;min-width:24px;height:24px;border-radius:50%;background:var(--el-color-primary-light-8);color:var(--el-color-primary);font-weight:600}.step-result{margin-top:10px}.step-result .el-select{width:120px}.conclusion-form{margin-top:16px}
</style>
