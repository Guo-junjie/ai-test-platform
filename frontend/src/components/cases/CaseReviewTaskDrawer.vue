<template>
  <el-drawer
    :model-value="modelValue"
    size="min(760px, 96vw)"
    destroy-on-close
    @open="loadTask"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <template #header>
      <div class="drawer-title">
        <div>
          <strong>{{ snapshot.title || task?.case?.title || '评审任务' }}</strong>
          <p v-if="task">第 {{ task.round }} 轮 · 绑定 v{{ task.case_version }} · {{ taskStatusLabel(task.status) }}</p>
        </div>
        <el-tag v-if="task" :type="taskStatusType(task.status)">{{ taskStatusLabel(task.status) }}</el-tag>
      </div>
    </template>

    <div v-loading="loading" class="review-task-body">
      <template v-if="task">
        <el-alert
          v-if="task.case?.current_version !== task.case_version"
          type="warning"
          :closable="false"
          show-icon
          title="当前用例版本已变化，本任务仍只展示提交时冻结的版本内容。"
        />
        <el-alert v-if="task.overdue" type="error" :closable="false" show-icon title="该评审任务已超过截止时间" class="overdue-alert" />
        <el-descriptions :column="2" border class="task-summary">
          <el-descriptions-item label="提交人">{{ task.submitter_name || '—' }}</el-descriptions-item>
          <el-descriptions-item label="提交时间">{{ formatTime(task.submitted_at) }}</el-descriptions-item>
          <el-descriptions-item label="截止时间">{{ formatTime(task.due_at) }}</el-descriptions-item>
          <el-descriptions-item label="通过进度">{{ task.approved_count }} / {{ task.reviewer_count }}</el-descriptions-item>
          <el-descriptions-item label="提交说明" :span="2">{{ task.submission_comment || '无' }}</el-descriptions-item>
        </el-descriptions>

        <section>
          <h3>评审人进度</h3>
          <el-table :data="task.reviewers || []" size="small" border>
            <el-table-column prop="reviewer_name" label="评审人" min-width="130" />
            <el-table-column label="状态" width="110">
              <template #default="{ row }"><el-tag size="small" :type="assignmentStatusType(row.status)">{{ assignmentStatusLabel(row.status) }}</el-tag></template>
            </el-table-column>
            <el-table-column prop="comment" label="评审意见" min-width="180"><template #default="{ row }">{{ row.comment || '—' }}</template></el-table-column>
            <el-table-column label="提交时间" width="170"><template #default="{ row }">{{ formatTime(row.decided_at) }}</template></el-table-column>
          </el-table>
        </section>

        <section>
          <h3>v{{ task.case_version }} 冻结内容</h3>
          <el-descriptions :column="2" border>
            <el-descriptions-item label="标题" :span="2">{{ snapshot.title || '—' }}</el-descriptions-item>
            <el-descriptions-item label="优先级">{{ snapshot.priority || '—' }}</el-descriptions-item>
            <el-descriptions-item label="执行类型">{{ snapshot.execution_kind === 'manual' ? '手工执行' : 'API 自动执行' }}</el-descriptions-item>
            <el-descriptions-item label="描述" :span="2">{{ snapshot.description || '—' }}</el-descriptions-item>
          </el-descriptions>
          <template v-if="snapshot.execution_kind === 'manual'">
            <h4>前置条件</h4><p class="plain-text">{{ snapshot.request_data?.preconditions || '无' }}</p>
            <h4>操作步骤</h4><ol><li v-for="(step, index) in snapshot.request_data?.steps || []" :key="index">{{ step }}</li></ol>
            <h4>预期结果</h4><p class="plain-text">{{ snapshot.expected_result?.text || '—' }}</p>
          </template>
          <template v-else>
            <div class="request-line"><el-tag>{{ snapshot.request_data?.method || 'GET' }}</el-tag><code>{{ snapshot.request_data?.url || '未配置路径' }}</code></div>
            <h4>请求配置</h4><pre>{{ prettyJson(snapshot.request_data) }}</pre>
            <h4>预期与断言</h4><pre>{{ prettyJson(snapshot.expected_result) }}</pre>
          </template>
        </section>
      </template>
      <el-empty v-else-if="!loading" description="评审任务不存在或已无权访问" />
    </div>

    <template #footer>
      <div class="drawer-footer">
        <el-button @click="emit('update:modelValue', false)">关闭</el-button>
        <template v-if="task?.can_review">
          <el-button type="warning" plain @click="openDecision('changes_requested')">退回修改</el-button>
          <el-button type="success" @click="openDecision('approve')">通过本版本</el-button>
        </template>
      </div>
    </template>
  </el-drawer>

  <el-dialog v-model="decisionVisible" :title="decision === 'approve' ? '通过本版本' : '退回修改'" width="500px" append-to-body>
    <el-alert
      :type="decision === 'approve' ? 'success' : 'warning'"
      :closable="false"
      show-icon
      :title="decision === 'approve' ? `确认通过 v${task?.case_version}？` : `将结束第 ${task?.round} 轮评审并退回提交人`"
      class="decision-alert"
    />
    <el-form label-position="top">
      <el-form-item :label="decision === 'approve' ? '评审意见（选填）' : '修改意见（必填）'" :required="decision === 'changes_requested'">
        <el-input v-model="decisionComment" type="textarea" :rows="4" maxlength="2000" show-word-limit />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="decisionVisible = false">取消</el-button>
      <el-button :type="decision === 'approve' ? 'success' : 'warning'" :loading="deciding" @click="submitDecision">确认提交</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { caseApi } from '@/api'

const props = defineProps<{ modelValue: boolean; taskId: string }>()
const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  decided: [task: any]
}>()

const loading = ref(false)
const task = ref<any>()
const decisionVisible = ref(false)
const decision = ref<'approve' | 'changes_requested'>('approve')
const decisionComment = ref('')
const deciding = ref(false)
const snapshot = computed(() => task.value?.version?.snapshot || {})

function taskStatusLabel(value: string) { return ({ pending: '进行中', approved: '已通过', changes_requested: '需修改', cancelled: '已取消' } as Record<string, string>)[value] || value }
function taskStatusType(value: string) { return ({ pending: 'warning', approved: 'success', changes_requested: 'danger', cancelled: 'info' } as Record<string, any>)[value] || 'info' }
function assignmentStatusLabel(value: string) { return ({ pending: '待评审', approved: '已通过', changes_requested: '已退回', cancelled: '已取消' } as Record<string, string>)[value] || value }
function assignmentStatusType(value: string) { return ({ pending: 'warning', approved: 'success', changes_requested: 'danger', cancelled: 'info' } as Record<string, any>)[value] || 'info' }
function formatTime(value?: string) { return value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '—' }
function prettyJson(value: any) { return JSON.stringify(value || {}, null, 2) }

async function loadTask() {
  if (!props.taskId) { task.value = undefined; return }
  loading.value = true
  try {
    const response: any = await caseApi.reviewTask(props.taskId)
    task.value = response?.data
  } finally {
    loading.value = false
  }
}

function openDecision(value: 'approve' | 'changes_requested') {
  decision.value = value
  decisionComment.value = ''
  decisionVisible.value = true
}

async function submitDecision() {
  if (decision.value === 'changes_requested' && !decisionComment.value.trim()) {
    ElMessage.warning('退回时必须填写修改意见')
    return
  }
  deciding.value = true
  try {
    const response: any = await caseApi.decideReviewTask(props.taskId, decision.value, decisionComment.value.trim())
    task.value = response?.data
    decisionVisible.value = false
    ElMessage.success(decision.value === 'approve' ? '评审结论已提交' : '已退回提交人修改')
    emit('decided', task.value)
  } finally {
    deciding.value = false
  }
}

defineExpose({ loadTask })

watch(() => props.taskId, (value, previous) => {
  if (props.modelValue && value && value !== previous) loadTask()
})
</script>

<style scoped>
.drawer-title { width: 100%; display: flex; align-items: center; justify-content: space-between; gap: 16px; padding-right: 12px; }
.drawer-title strong { font-size: 17px; }
.drawer-title p { margin: 5px 0 0; color: var(--el-text-color-secondary); font-size: 12px; }
.review-task-body { min-height: 520px; }
.review-task-body section { margin-top: 22px; }
.review-task-body h3 { margin: 0 0 12px; font-size: 15px; }
.review-task-body h4 { margin: 18px 0 8px; font-size: 13px; }
.task-summary { margin-top: 14px; }
.overdue-alert { margin-top: 12px; }
.plain-text { white-space: pre-wrap; word-break: break-word; }
.request-line { display: flex; align-items: center; gap: 10px; margin-top: 16px; }
.request-line code { word-break: break-all; }
pre { max-height: 280px; margin: 0; padding: 12px; overflow: auto; white-space: pre-wrap; word-break: break-word; background: var(--el-fill-color-light); border-radius: 6px; font-size: 12px; }
ol { margin: 0; padding-left: 24px; line-height: 1.9; }
.drawer-footer { text-align: right; }
.decision-alert { margin-bottom: 16px; }
</style>
