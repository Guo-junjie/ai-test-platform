<template>
  <div class="test-run-page">
    <!-- Task list -->
    <el-card shadow="hover">
      <template #header>
        <div class="card-header">
          <span>测试任务</span>
          <el-button type="primary" @click="showCreateDialog = true">
            <el-icon><Plus /></el-icon>
            新建测试任务
          </el-button>
        </div>
      </template>

      <el-table
        :data="testRuns"
        v-loading="loading"
        stripe
        style="width: 100%"
        @row-click="handleRowClick"
      >
        <el-table-column label="任务 ID" width="120">
          <template #default="{ row }">
            <span class="mono-text">{{ row.id.substring(0, 8) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="120">
          <template #default="{ row }">
            <el-tag :type="statusTagType(row.status)" size="small">
              {{ statusLabel(row.status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="进度" width="200">
          <template #default="{ row }">
            <el-progress
              :percentage="row.progress || 0"
              :status="progressStatus(row.status)"
              :stroke-width="14"
            />
          </template>
        </el-table-column>
        <el-table-column prop="source_type" label="数据源" width="100" />
        <el-table-column prop="source_ref" label="来源" min-width="200" show-overflow-tooltip />
        <el-table-column prop="branch" label="分支" width="100" />
        <el-table-column label="创建时间" width="180">
          <template #default="{ row }">
            {{ formatTime(row.created_at) }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="120" fixed="right">
          <template #default="{ row }">
            <el-button
              size="small"
              type="danger"
              :disabled="['completed', 'failed', 'cancelled'].includes(row.status)"
              @click.stop="handleCancel(row)"
            >
              取消
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <el-empty
        v-if="!loading && testRuns.length === 0"
        description="暂无测试任务，点击右上角创建"
      />
    </el-card>

    <!-- Task detail dialog -->
    <el-dialog
      v-model="detailVisible"
      :title="`任务详情 - ${selectedRun?.id?.substring(0, 8) || ''}`"
      width="800px"
    >
      <div v-if="selectedRun" class="detail-content">
        <el-descriptions :column="2" border>
          <el-descriptions-item label="任务 ID">
            <span class="mono-text">{{ selectedRun.id }}</span>
          </el-descriptions-item>
          <el-descriptions-item label="状态">
            <el-tag :type="statusTagType(selectedRun.status)" size="small">
              {{ statusLabel(selectedRun.status) }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="进度">
            <el-progress
              :percentage="detailProgress"
              :status="progressStatus(selectedRun.status)"
              :stroke-width="16"
            />
          </el-descriptions-item>
          <el-descriptions-item label="当前步骤">
            {{ detailStep || 'N/A' }}
          </el-descriptions-item>
          <el-descriptions-item label="数据源">
            {{ selectedRun.source_type }}
          </el-descriptions-item>
          <el-descriptions-item label="来源">
            <span class="mono-text">{{ selectedRun.source_ref || '-' }}</span>
          </el-descriptions-item>
          <el-descriptions-item label="分支">
            {{ selectedRun.branch || '-' }}
          </el-descriptions-item>
          <el-descriptions-item label="Commit">
            <span class="mono-text">{{ selectedRun.commit_sha?.substring(0, 12) || '-' }}</span>
          </el-descriptions-item>
          <el-descriptions-item v-if="selectedRun.error_message" label="错误信息" :span="2">
            <span class="error-text">{{ selectedRun.error_message }}</span>
          </el-descriptions-item>
        </el-descriptions>

        <!-- Analysis result summary -->
        <div v-if="selectedRun.analysis_result" class="analysis-summary">
          <el-divider content-position="left">代码解析结果</el-divider>
          <el-descriptions :column="3" border>
            <el-descriptions-item label="技术栈">
              <el-tag size="small">{{ selectedRun.analysis_result.tech_stack?.stack || 'N/A' }}</el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="框架">
              {{ selectedRun.analysis_result.tech_stack?.framework || 'N/A' }}
            </el-descriptions-item>
            <el-descriptions-item label="API 数量">
              {{ selectedRun.analysis_result.total_apis || 0 }}
            </el-descriptions-item>
          </el-descriptions>
        </div>
      </div>
    </el-dialog>

    <!-- Create test run dialog -->
    <el-dialog
      v-model="showCreateDialog"
      title="新建测试任务"
      width="600px"
      :close-on-click-modal="false"
    >
      <el-form :model="form" label-width="100px">
        <el-form-item label="数据源类型">
          <el-radio-group v-model="form.source_type">
            <el-radio-button value="github">GitHub 仓库</el-radio-button>
            <el-radio-button value="svn">SVN 仓库</el-radio-button>
            <el-radio-button value="upload">上传代码</el-radio-button>
          </el-radio-group>
        </el-form-item>

        <!-- GitHub fields -->
        <template v-if="form.source_type === 'github'">
          <el-form-item label="仓库 URL" required>
            <el-input
              v-model="form.repo_url"
              placeholder="https://github.com/owner/repo"
            />
          </el-form-item>
          <el-form-item label="GitHub Token">
            <el-input
              v-model="form.github_token"
              type="password"
              show-password
              placeholder="ghp_xxxxxxxxxxxx"
            />
          </el-form-item>
          <el-form-item label="分支">
            <el-input v-model="form.branch" placeholder="main" />
          </el-form-item>
        </template>

        <!-- SVN fields -->
        <template v-if="form.source_type === 'svn'">
          <el-form-item label="SVN URL" required>
            <el-input
              v-model="form.svn_url"
              placeholder="https://svn.example.com/svn/project"
            />
          </el-form-item>
          <el-form-item label="用户名">
            <el-input v-model="form.svn_username" placeholder="SVN 用户名" />
          </el-form-item>
          <el-form-item label="密码">
            <el-input
              v-model="form.svn_password"
              type="password"
              show-password
              placeholder="SVN 密码"
            />
          </el-form-item>
        </template>

        <!-- Upload fields -->
        <template v-if="form.source_type === 'upload'">
          <el-form-item label="上传代码">
            <el-upload
              drag
              :auto-upload="true"
              :show-file-list="false"
              :http-request="handleUpload"
              accept=".zip,.tar.gz,.tgz,.tar"
            >
              <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
              <div class="el-upload__text">
                拖拽文件到此处，或<em>点击上传</em>
              </div>
              <template #tip>
                <div class="el-upload__tip">支持 ZIP / TAR.GZ 格式压缩包</div>
              </template>
            </el-upload>
            <div v-if="form.upload_file_path" class="upload-path">
              已上传: <span class="mono-text">{{ form.upload_file_path }}</span>
            </div>
          </el-form-item>
        </template>
      </el-form>

      <template #footer>
        <el-button @click="showCreateDialog = false">取消</el-button>
        <el-button
          type="primary"
          :loading="creating"
          @click="handleCreate"
        >
          启动测试
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted, onUnmounted } from 'vue'
import { Plus, UploadFilled } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { UploadRequestOptions } from 'element-plus'
import { testRunApi, uploadApi } from '@/api'

// ==================== State ====================

const loading = ref(false)
const creating = ref(false)
const showCreateDialog = ref(false)
const detailVisible = ref(false)
const selectedRun = ref<any>(null)
const testRuns = ref<any[]>([])

const detailProgress = ref(0)
const detailStep = ref('')
const progressTimer = ref<number | null>(null)

const form = reactive({
  source_type: 'github',
  repo_url: '',
  github_token: '',
  branch: 'main',
  svn_url: '',
  svn_username: '',
  svn_password: '',
  upload_file_path: '',
})

// ==================== Methods ====================

async function loadTestRuns() {
  loading.value = true
  try {
    const res: any = await testRunApi.list()
    testRuns.value = res?.data?.list || []

    // Auto-poll for in-progress tasks
    const hasInProgress = testRuns.value.some(
      (r) => !['completed', 'failed', 'cancelled'].includes(r.status)
    )
    if (hasInProgress) {
      schedulePoll()
    }
  } catch {
    testRuns.value = []
  } finally {
    loading.value = false
  }
}

function schedulePoll() {
  if (progressTimer.value) return
  progressTimer.value = window.setInterval(() => {
    loadTestRuns()
    // Also update detail if open
    if (detailVisible.value && selectedRun.value) {
      updateDetailProgress(selectedRun.value.id)
    }
    // Stop polling if no in-progress tasks
    const stillInProgress = testRuns.value.some(
      (r) => !['completed', 'failed', 'cancelled'].includes(r.status)
    )
    if (!stillInProgress && progressTimer.value) {
      clearInterval(progressTimer.value)
      progressTimer.value = null
    }
  }, 3000)
}

async function updateDetailProgress(runId: string) {
  try {
    const res: any = await testRunApi.getProgress(runId)
    const data = res?.data
    if (data) {
      detailProgress.value = data.progress || 0
      detailStep.value = data.step || ''
    }
  } catch {
    // Ignore polling errors
  }
}

function handleRowClick(row: any) {
  selectedRun.value = row
  detailProgress.value = row.progress || 0
  detailStep.value = ''
  detailVisible.value = true

  if (!['completed', 'failed', 'cancelled'].includes(row.status)) {
    updateDetailProgress(row.id)
    schedulePoll()
  }
}

async function handleCreate() {
  // Validate
  if (form.source_type === 'github' && !form.repo_url) {
    ElMessage.warning('请输入仓库 URL')
    return
  }
  if (form.source_type === 'svn' && !form.svn_url) {
    ElMessage.warning('请输入 SVN URL')
    return
  }
  if (form.source_type === 'upload' && !form.upload_file_path) {
    ElMessage.warning('请先上传代码文件')
    return
  }

  creating.value = true
  try {
    await testRunApi.create({ ...form })
    ElMessage.success('测试任务已创建')
    showCreateDialog.value = false
    // Reset form
    Object.assign(form, {
      source_type: 'github',
      repo_url: '',
      github_token: '',
      branch: 'main',
      svn_url: '',
      svn_username: '',
      svn_password: '',
      upload_file_path: '',
    })
    // Reload list
    loadTestRuns()
  } catch {
    // Error handled by axios interceptor
  } finally {
    creating.value = false
  }
}

async function handleUpload(options: UploadRequestOptions) {
  try {
    const res: any = await uploadApi.upload(options.file as File)
    form.upload_file_path = res?.data?.local_path || ''
    ElMessage.success('文件上传成功')
  } catch {
    // Error handled by axios interceptor
  }
}

async function handleCancel(row: any) {
  try {
    await ElMessageBox.confirm(
      `确定要取消任务「${row.id.substring(0, 8)}」吗？`,
      '确认取消',
      { type: 'warning' }
    )
    await testRunApi.cancel(row.id)
    ElMessage.success('任务已取消')
    loadTestRuns()
  } catch {
    // User cancelled
  }
}

function statusTagType(status: string): string {
  const map: Record<string, string> = {
    pending: 'info',
    pulling: 'warning',
    analyzing: 'warning',
    generating: 'warning',
    executing: 'primary',
    analyzing_defects: 'warning',
    reporting: 'warning',
    completed: 'success',
    failed: 'danger',
    cancelled: 'info',
  }
  return map[status] || 'info'
}

function statusLabel(status: string): string {
  const map: Record<string, string> = {
    pending: '等待中',
    pulling: '拉取代码',
    analyzing: '解析代码',
    generating: '生成用例',
    executing: '执行测试',
    analyzing_defects: '分析缺陷',
    reporting: '生成报告',
    completed: '已完成',
    failed: '失败',
    cancelled: '已取消',
  }
  return map[status] || status
}

function progressStatus(status: string): string {
  if (status === 'completed') return 'success'
  if (status === 'failed') return 'exception'
  return ''
}

function formatTime(time: string): string {
  if (!time) return '-'
  try {
    return new Date(time).toLocaleString('zh-CN')
  } catch {
    return time
  }
}

// ==================== Lifecycle ====================

onMounted(() => {
  loadTestRuns()
})

onUnmounted(() => {
  if (progressTimer.value) {
    clearInterval(progressTimer.value)
    progressTimer.value = null
  }
})
</script>

<style scoped>
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.mono-text {
  font-family: 'Courier New', Consolas, monospace;
  font-size: 13px;
  color: #606266;
  word-break: break-all;
}

.error-text {
  color: #f56c6c;
  font-size: 13px;
}

.detail-content {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.analysis-summary {
  margin-top: 8px;
}

.upload-path {
  margin-top: 8px;
  color: #67c23a;
  font-size: 13px;
}
</style>
