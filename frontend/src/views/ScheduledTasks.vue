<template>
  <div class="scheduled-tasks-page">
    <el-card shadow="hover">
      <template #header>
        <div class="card-header">
          <span>定时任务管理</span>
          <el-button type="primary" @click="openCreateDialog">
            <el-icon><Plus /></el-icon>
            新建任务
          </el-button>
        </div>
      </template>

      <div class="filter-bar" style="margin-bottom: 16px;">
        <el-select v-model="projectId" placeholder="选择项目" filterable style="width: 300px;" @change="loadTasks">
          <el-option v-for="p in projects" :key="p.id" :label="p.name" :value="p.id" />
        </el-select>
      </div>

      <el-table :data="tasks" v-loading="loading" style="width: 100%">
        <el-table-column prop="name" label="名称" />
        <el-table-column prop="cron_expression" label="Cron 表达式" width="140" />
        <el-table-column prop="target_type" label="目标类型" width="120" />
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="row.status === 'active' ? 'success' : 'info'">
              {{ row.status === 'active' ? '启用' : '暂停' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="上次执行" width="180">
          <template #default="{ row }">
            {{ row.last_run_at ? formatTime(row.last_run_at) : '—' }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="280">
          <template #default="{ row }">
            <el-button size="small" plain @click="viewHistory(row)">历史</el-button>
            <el-button size="small" plain @click="openEditDialog(row)">编辑</el-button>
            <el-button
              size="small"
              :type="row.status === 'active' ? 'warning' : 'success'"
              plain
              @click="toggleTask(row)"
            >
              {{ row.status === 'active' ? '暂停' : '启用' }}
            </el-button>
            <el-button size="small" type="danger" plain @click="handleDelete(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 新建/编辑对话框 -->
    <el-dialog
      v-model="dialogVisible"
      :title="isEdit ? '编辑定时任务' : '新建定时任务'"
      width="640px"
      destroy-on-close
    >
      <el-form ref="formRef" :model="form" :rules="formRules" label-width="130px">
        <el-form-item label="任务名称" prop="name">
          <el-input v-model="form.name" placeholder="例如：每日回归测试" />
        </el-form-item>
        <el-form-item label="任务描述">
          <el-input v-model="form.description" type="textarea" :rows="2" />
        </el-form-item>
        <el-form-item label="调度描述（NL）">
          <el-input
            v-model="form.nl_schedule"
            placeholder="例如：每天早上8点 / 每周一 / 每月1号"
            @blur="previewCron"
          />
        </el-form-item>
        <el-form-item label="Cron 表达式" prop="cron_expression">
          <el-input v-model="form.cron_expression" placeholder="自动解析或手动输入，例如：0 8 * * *" />
        </el-form-item>
        <el-alert
          v-if="cronPreview"
          :title="`解析结果：${cronPreview.cron_expression}`"
          :description="cronPreview.description"
          type="info"
          :closable="false"
          style="margin-bottom: 16px;"
        />
        <el-form-item label="目标类型" prop="target_type">
          <el-select v-model="form.target_type" style="width: 100%;">
            <el-option label="测试场景" value="scenario" />
            <el-option label="用例集合" value="case_collection" />
          </el-select>
        </el-form-item>
        <el-form-item label="目标 ID">
          <el-input v-model="form.target_id" placeholder="场景 ID 或用例集合 ID" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submitForm">确定</el-button>
      </template>
    </el-dialog>

    <!-- 执行历史对话框 -->
    <el-dialog v-model="historyVisible" title="执行历史" width="720px">
      <div v-loading="historyLoading">
        <el-table :data="history" size="small" border>
          <el-table-column prop="status" label="状态" width="100">
            <template #default="{ row }">
              <el-tag :type="statusTagType(row.status)" size="small">{{ row.status }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="开始时间" width="180">
            <template #default="{ row }">
              {{ row.started_at ? formatTime(row.started_at) : '—' }}
            </template>
          </el-table-column>
          <el-table-column label="结束时间" width="180">
            <template #default="{ row }">
              {{ row.finished_at ? formatTime(row.finished_at) : '—' }}
            </template>
          </el-table-column>
          <el-table-column prop="error_message" label="错误信息" show-overflow-tooltip />
        </el-table>
        <el-empty v-if="!historyLoading && !history.length" description="暂无执行历史" />
      </div>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from 'element-plus'
import { scheduledTaskApi, projectApi } from '@/api'
import dayjs from 'dayjs'

const projectId = ref('')
const projects = ref<any[]>([])
const tasks = ref<any[]>([])
const loading = ref(false)
const submitting = ref(false)

const dialogVisible = ref(false)
const isEdit = ref(false)
const currentId = ref('')
const formRef = ref<FormInstance>()
const cronPreview = ref<any>(null)

const historyVisible = ref(false)
const historyLoading = ref(false)
const history = ref<any[]>([])

const form = reactive({
  name: '',
  description: '',
  nl_schedule: '',
  cron_expression: '',
  target_type: 'scenario',
  target_id: '',
})

const formRules: FormRules = {
  name: [{ required: true, message: '请输入任务名称', trigger: 'blur' }],
  cron_expression: [{ required: true, message: '请输入或解析 Cron 表达式', trigger: 'blur' }],
  target_type: [{ required: true, message: '请选择目标类型', trigger: 'change' }],
}

function formatTime(t: string): string {
  return dayjs(t).format('YYYY-MM-DD HH:mm:ss')
}

function statusTagType(status: string): string {
  if (status === 'success' || status === 'completed') return 'success'
  if (status === 'failed' || status === 'error') return 'danger'
  return 'info'
}

async function loadProjects(): Promise<void> {
  try {
    const res: any = await projectApi.getList()
    projects.value = Array.isArray(res?.data) ? res.data : (res?.data?.items || res?.data?.list || [])
  } catch {
    projects.value = []
  }
}

async function loadTasks(): Promise<void> {
  if (!projectId.value) {
    tasks.value = []
    return
  }
  loading.value = true
  try {
    const res: any = await scheduledTaskApi.listTasks(projectId.value)
    tasks.value = Array.isArray(res?.data) ? res.data : (res?.data?.items || res?.data?.list || [])
  } catch {
    tasks.value = []
  } finally {
    loading.value = false
  }
}

function openCreateDialog(): void {
  if (!projectId.value) {
    ElMessage.warning('请先选择项目')
    return
  }
  isEdit.value = false
  currentId.value = ''
  cronPreview.value = null
  Object.assign(form, {
    name: '', description: '', nl_schedule: '', cron_expression: '',
    target_type: 'scenario', target_id: '',
  })
  dialogVisible.value = true
}

function openEditDialog(row: any): void {
  isEdit.value = true
  currentId.value = row.id
  cronPreview.value = null
  Object.assign(form, {
    name: row.name,
    description: row.description || '',
    nl_schedule: row.nl_schedule || '',
    cron_expression: row.cron_expression || '',
    target_type: row.target_type || 'scenario',
    target_id: row.target_id || '',
  })
  dialogVisible.value = true
}

async function previewCron(): Promise<void> {
  if (!form.nl_schedule?.trim()) {
    cronPreview.value = null
    return
  }
  try {
    const res: any = await scheduledTaskApi.parseCron({ nl_schedule: form.nl_schedule })
    cronPreview.value = res?.data ?? res
    if (cronPreview.value?.cron_expression) {
      form.cron_expression = cronPreview.value.cron_expression
    }
  } catch {
    cronPreview.value = null
  }
}

async function submitForm(): Promise<void> {
  if (!formRef.value) return
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return

  submitting.value = true
  try {
    const payload: Record<string, any> = {
      name: form.name,
      description: form.description,
      nl_schedule: form.nl_schedule,
      cron_expression: form.cron_expression,
      target_type: form.target_type,
      target_id: form.target_id || null,
    }
    if (isEdit.value) {
      await scheduledTaskApi.updateTask(currentId.value, payload)
      ElMessage.success('更新成功')
    } else {
      payload.project_id = projectId.value
      await scheduledTaskApi.createTask(payload)
      ElMessage.success('创建成功')
    }
    dialogVisible.value = false
    await loadTasks()
  } catch (e: any) {
    ElMessage.error(e?.message || '保存失败')
  } finally {
    submitting.value = false
  }
}

async function toggleTask(row: any): Promise<void> {
  try {
    await scheduledTaskApi.toggleTask(row.id)
    ElMessage.success(row.status === 'active' ? '已暂停' : '已启用')
    await loadTasks()
  } catch (e: any) {
    ElMessage.error(e?.message || '操作失败')
  }
}

async function handleDelete(row: any): Promise<void> {
  try {
    await ElMessageBox.confirm(
      `确认删除定时任务「${row.name}」吗？`,
      '删除确认',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }
    )
  } catch {
    return
  }
  try {
    await scheduledTaskApi.deleteTask(row.id)
    ElMessage.success('删除成功')
    await loadTasks()
  } catch (e: any) {
    ElMessage.error(e?.message || '删除失败')
  }
}

async function viewHistory(row: any): Promise<void> {
  historyVisible.value = true
  historyLoading.value = true
  history.value = []
  try {
    const res: any = await scheduledTaskApi.getHistory(row.id)
    history.value = res?.data?.items || res?.data || []
  } catch {
    history.value = []
  } finally {
    historyLoading.value = false
  }
}

onMounted(() => {
  loadProjects()
})
</script>

<style scoped>
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
</style>
