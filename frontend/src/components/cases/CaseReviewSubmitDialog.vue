<template>
  <el-dialog
    :model-value="modelValue"
    title="发起用例评审"
    width="560px"
    destroy-on-close
    @open="prepare"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <el-alert
      type="info"
      :closable="false"
      show-icon
      :title="`将冻结并评审“${caseItem?.title || '当前用例'}”的 v${caseItem?.version || 1} 版本`"
      description="全部指定评审人通过后，用例才会进入已批准状态；任一人退回，本轮评审立即结束。"
      class="review-rule"
    />
    <el-form ref="formRef" :model="form" :rules="rules" label-position="top">
      <el-form-item label="评审人" prop="reviewer_ids">
        <el-select
          v-model="form.reviewer_ids"
          multiple
          filterable
          collapse-tags
          collapse-tags-tooltip
          :loading="loadingReviewers"
          placeholder="选择项目评审人"
          style="width: 100%"
        >
          <el-option
            v-for="reviewer in reviewers"
            :key="reviewer.id"
            :label="`${reviewer.username} · ${roleLabel(reviewer.role)}`"
            :value="reviewer.id"
          />
        </el-select>
        <div v-if="!loadingReviewers && !reviewers.length" class="form-hint">
          当前项目没有可用评审人，请先添加测试经理，或由管理员参与评审。
        </div>
      </el-form-item>
      <el-form-item label="截止时间" prop="due_at">
        <el-date-picker
          v-model="form.due_at"
          type="datetime"
          placeholder="可选；用于明确评审时限"
          :disabled-date="disablePastDate"
          style="width: 100%"
        />
      </el-form-item>
      <el-form-item label="提交说明" prop="comment">
        <el-input
          v-model="form.comment"
          type="textarea"
          :rows="4"
          maxlength="2000"
          show-word-limit
          placeholder="说明本轮关注点、关联变更或验证范围"
        />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="emit('update:modelValue', false)">取消</el-button>
      <el-button type="primary" :loading="submitting" :disabled="!reviewers.length" @click="submit">
        创建评审任务
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { reactive, ref } from 'vue'
import type { FormInstance, FormRules } from 'element-plus'
import { ElMessage } from 'element-plus'
import { caseApi } from '@/api'

const props = defineProps<{
  modelValue: boolean
  projectId: string
  caseItem: any
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  submitted: [task: any]
}>()

const formRef = ref<FormInstance>()
const reviewers = ref<any[]>([])
const loadingReviewers = ref(false)
const submitting = ref(false)
const form = reactive({ reviewer_ids: [] as string[], due_at: null as Date | null, comment: '' })
const rules: FormRules = {
  reviewer_ids: [{ required: true, type: 'array', min: 1, message: '请至少选择一名评审人', trigger: 'change' }],
}

function roleLabel(role: string) {
  return ({ super_admin: '超级管理员', admin: '管理员', test_manager: '测试经理' } as Record<string, string>)[role] || role
}

function disablePastDate(date: Date) {
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  return date.getTime() < today.getTime()
}

async function prepare() {
  form.reviewer_ids = []
  form.due_at = null
  form.comment = ''
  formRef.value?.clearValidate()
  if (!props.projectId) return
  loadingReviewers.value = true
  try {
    const response: any = await caseApi.reviewers(props.projectId)
    reviewers.value = response?.data || []
  } finally {
    loadingReviewers.value = false
  }
}

async function submit() {
  if (!props.caseItem?.id || !await formRef.value?.validate().catch(() => false)) return
  submitting.value = true
  try {
    const response: any = await caseApi.createReviewTask(props.caseItem.id, {
      reviewer_ids: form.reviewer_ids,
      due_at: form.due_at ? form.due_at.toISOString() : null,
      comment: form.comment.trim(),
    })
    ElMessage.success('评审任务已创建并通知评审人')
    emit('update:modelValue', false)
    emit('submitted', response?.data)
  } finally {
    submitting.value = false
  }
}
</script>

<style scoped>
.review-rule { margin-bottom: 18px; }
.form-hint { margin-top: 6px; color: var(--el-color-warning); font-size: 12px; }
</style>
