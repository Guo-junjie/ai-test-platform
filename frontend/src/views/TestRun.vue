<template>
  <div class="test-run-page">
    <!-- Create test run card with 3 mode tabs -->
    <el-card shadow="hover" class="create-card">
      <template #header>
        <div class="card-header">
          <span>新建测试任务</span>
        </div>
      </template>

      <el-tabs v-model="activeMode" class="mode-tabs">
        <!-- ==================== Mode 1: Auto（拉代码 + AI 生成） ==================== -->
        <el-tab-pane label="代码仓库" name="auto">
          <div class="mode-desc">
            全自动流水线：拉取仓库代码 → AI 解析接口 → AI 生成用例 → 执行 → 缺陷分析 → 测试报告。
            适合首次接入项目，无需提前准备用例。
          </div>
          <el-form :model="form" label-width="100px">
            <el-form-item label="数据源类型">
              <el-radio-group v-model="form.source_type">
                <el-radio-button value="github">GitHub 仓库</el-radio-button>
                <el-radio-button value="svn">SVN 仓库</el-radio-button>
              </el-radio-group>
            </el-form-item>

            <template v-if="form.source_type === 'github'">
              <el-form-item label="仓库 URL" required>
                <el-input v-model="form.repo_url" placeholder="https://github.com/owner/repo" />
              </el-form-item>
              <el-form-item label="GitHub Token">
                <el-input v-model="form.github_token" type="password" show-password placeholder="ghp_xxxxxxxxxxxx" />
              </el-form-item>
              <el-form-item label="分支">
                <el-input v-model="form.branch" placeholder="main" />
              </el-form-item>
            </template>

            <template v-if="form.source_type === 'svn'">
              <el-form-item label="SVN URL" required>
                <el-input v-model="form.svn_url" placeholder="https://svn.example.com/svn/project" />
              </el-form-item>
              <el-form-item label="用户名">
                <el-input v-model="form.svn_username" placeholder="SVN 用户名" />
              </el-form-item>
              <el-form-item label="密码">
                <el-input v-model="form.svn_password" type="password" show-password placeholder="SVN 密码" />
              </el-form-item>
            </template>

            <el-form-item label="归属项目">
              <el-select v-model="form.project_id" placeholder="选择项目（可留空自动创建临时项目）" clearable style="width: 100%">
                <el-option v-for="p in projects" :key="p.id" :label="p.name" :value="p.id" />
              </el-select>
            </el-form-item>
          </el-form>
          <div class="form-actions">
            <el-button type="primary" :loading="creating" @click="handleCreateAuto">
              <el-icon><Plus /></el-icon>
              启动测试
            </el-button>
          </div>
        </el-tab-pane>

        <!-- ==================== Mode 2: Test Plan（已有用例，直接执行） ==================== -->
        <el-tab-pane label="测试计划" name="plan">
          <div class="mode-desc">
            按计划执行：跳过代码拉取与 AI 生成，直接运行计划内已启用的用例，适合回归测试。
            <br>
            还没有计划？到<b>「用例库」</b>选择用例 → 点<b>「加入计划」</b>→ 选「新建计划」即可创建。
          </div>
          <el-empty
            v-if="!plansLoading && plans.length === 0"
            description="还没有测试计划 —— 去「用例库」选择用例，点「加入计划」新建"
          >
            <el-button type="primary" plain @click="loadPlans">重新加载</el-button>
          </el-empty>
          <el-form v-else label-width="100px">
            <el-form-item label="测试计划" required>
              <div class="plan-select-row">
                <el-select
                  v-model="selectedPlanId"
                  placeholder="选择测试计划"
                  filterable
                  clearable
                  :loading="plansLoading"
                  class="plan-select"
                >
                  <el-option
                    v-for="p in plans"
                    :key="p.id"
                    :label="`${p.name}（${p.case_count ?? 0} 用例）`"
                    :value="p.id"
                  >
                    <span style="float: left">{{ p.name }}</span>
                    <span style="float: right; color: var(--el-text-color-secondary); font-size: 12px">
                      {{ p.project_name || '—' }} · {{ p.case_count ?? 0 }} 用例
                    </span>
                  </el-option>
                </el-select>
                <el-button :loading="plansLoading" @click="loadPlans">刷新</el-button>
              </div>
            </el-form-item>

            <el-form-item v-if="selectedPlan" label="计划概要">
              <el-descriptions :column="2" border size="small">
                <el-descriptions-item label="所属项目">{{ selectedPlan.project_name || '—' }}</el-descriptions-item>
                <el-descriptions-item label="状态">
                  <el-tag size="small" :type="selectedPlan.status === 'active' ? 'success' : 'info'">
                    {{ selectedPlan.status === 'active' ? '启用中' : '已停用' }}
                  </el-tag>
                </el-descriptions-item>
                <el-descriptions-item label="启用用例">{{ selectedPlan.enabled_case_count ?? selectedPlan.case_count ?? 0 }}</el-descriptions-item>
                <el-descriptions-item label="上次执行">{{ formatTime(selectedPlan.last_executed_at) || '从未执行' }}</el-descriptions-item>
                <el-descriptions-item v-if="selectedPlan.description" label="描述" :span="2">
                  {{ selectedPlan.description }}
                </el-descriptions-item>
              </el-descriptions>
            </el-form-item>
          </el-form>
          <div class="form-actions">
            <el-button :disabled="!selectedPlanId" @click="selectedPlanId = ''">清空选择</el-button>
            <el-button
              type="primary"
              :loading="creating"
              :disabled="!selectedPlanId"
              @click="handleExecutePlan"
            >
              <el-icon><VideoPlay /></el-icon>
              执行计划
            </el-button>
          </div>
        </el-tab-pane>

        <!-- ==================== Mode 3: Upload（zip 上传） ==================== -->
        <el-tab-pane label="上传代码" name="upload">
          <div class="mode-desc">
            全自动流水线：上传代码压缩包 → AI 解析接口 → AI 生成用例 → 执行 → 缺陷分析 → 测试报告。
            适合代码在内网/本地、无法直连仓库的场景。
          </div>
          <el-form :model="form" label-width="100px">
            <el-form-item label="上传代码">
              <el-upload
                drag
                :auto-upload="true"
                :show-file-list="false"
                :http-request="handleUpload"
                accept=".zip,.tar.gz,.tgz,.tar"
              >
                <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
                <div class="el-upload__text">拖拽文件到此处，或<em>点击上传</em></div>
                <template #tip>
                  <div class="el-upload__tip">支持 ZIP / TAR.GZ 格式压缩包</div>
                </template>
              </el-upload>
              <div v-if="form.upload_file_path" class="upload-path">
                已上传: <span class="mono-text">{{ form.upload_file_path }}</span>
              </div>
            </el-form-item>
            <el-form-item label="归属项目">
              <el-select v-model="form.project_id" placeholder="选择项目（可留空自动创建临时项目）" clearable style="width: 100%">
                <el-option v-for="p in projects" :key="p.id" :label="p.name" :value="p.id" />
              </el-select>
            </el-form-item>
          </el-form>
          <div class="form-actions">
            <el-button type="primary" :loading="creating" @click="handleCreateUpload">
              <el-icon><Plus /></el-icon>
              启动测试
            </el-button>
          </div>
        </el-tab-pane>
      </el-tabs>
    </el-card>

    <!-- Task list -->
    <el-card shadow="hover" class="list-card">
      <template #header>
        <div class="card-header">
          <span>测试任务</span>
          <div style="display: flex; gap: 8px; align-items: center">
            <el-select v-model="filterProjectId" placeholder="全部项目" clearable style="width: 170px" @change="loadTestRuns">
              <el-option v-for="p in projects" :key="p.id" :label="p.name" :value="p.id" />
            </el-select>
            <el-select v-model="filterMode" placeholder="全部模式" clearable style="width: 140px" @change="loadTestRuns">
              <el-option label="自动" value="auto" />
              <el-option label="测试计划" value="plan" />
              <el-option label="上传代码" value="upload" />
            </el-select>
            <el-select v-model="filterStatus" placeholder="全部状态" clearable style="width: 140px" @change="loadTestRuns">
              <el-option v-for="(label, key) in STATUS_OPTIONS" :key="key" :label="label" :value="key" />
            </el-select>
          </div>
        </div>
      </template>

      <el-table :data="testRuns" v-loading="loading" stripe style="width: 100%" @row-click="handleRowClick">
        <el-table-column label="模式" width="80">
          <template #default="{ row }">
            <el-tag size="small" :type="row.plan_id ? 'success' : 'primary'" effect="plain">
              {{ row.plan_id ? '计划' : (row.source_type || '—') }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="项目" min-width="120" show-overflow-tooltip>
          <template #default="{ row }">
            <span class="mono-text">{{ row.project_name || '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="任务 ID" width="110">
          <template #default="{ row }">
            <span class="mono-text">{{ row.id?.substring(0, 8) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <el-tag :type="statusTagType(row.status)" size="small">
              {{ statusLabel(row.status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="进度" width="180">
          <template #default="{ row }">
            <el-progress :percentage="row.progress || 0" :status="progressStatus(row.status)" :stroke-width="14" />
          </template>
        </el-table-column>
        <el-table-column label="当前步骤" min-width="160" show-overflow-tooltip>
          <template #default="{ row }">
            <span class="step-text">{{ statusLabel(row.current_step || row.status) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="来源" min-width="180" show-overflow-tooltip>
          <template #default="{ row }">
            <span class="mono-text source-text">{{ row.source_ref || (row.plan_id ? '测试计划' : '—') }}</span>
          </template>
        </el-table-column>
        <el-table-column label="创建时间" width="170">
          <template #default="{ row }">
            <span class="time-text">{{ formatTime(row.created_at) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="100" fixed="right">
          <template #default="{ row }">
            <el-button size="small" type="danger" :disabled="['completed','failed','cancelled'].includes(row.status)" @click.stop="handleCancel(row)">
              取消
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <el-empty v-if="!loading && testRuns.length === 0" description="暂无测试任务，点击上方任一模式创建" />
    </el-card>

    <!-- Task detail dialog -->
    <el-dialog v-model="detailVisible" :title="`任务详情 - ${selectedRun?.id?.substring(0, 8) || ''}`" width="880px">
      <div v-if="selectedRun" class="detail-content">
        <el-descriptions :column="2" border>
          <el-descriptions-item label="模式">
            <el-tag size="small" :type="selectedRun.plan_id ? 'success' : 'primary'" effect="plain">
              {{ selectedRun.plan_id ? '测试计划' : (selectedRun.source_type || '—') }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="状态">
            <el-tag :type="statusTagType(selectedRun.status)" size="small">
              {{ statusLabel(selectedRun.status) }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="任务 ID">
            <span class="mono-text">{{ selectedRun.id }}</span>
          </el-descriptions-item>
          <el-descriptions-item label="当前步骤">
            <span class="step-text">{{ statusLabel(detailStep || selectedRun.current_step || selectedRun.status) }}</span>
          </el-descriptions-item>
          <el-descriptions-item label="进度">
            <el-progress :percentage="detailProgress" :status="progressStatus(selectedRun.status)" :stroke-width="16" />
          </el-descriptions-item>
          <el-descriptions-item label="来源">
            <span class="mono-text">{{ selectedRun.source_ref || (selectedRun.plan_id ? '测试计划' : '-') }}</span>
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

        <!-- Step timeline (phase 6b) -->
        <el-divider content-position="left">执行步骤</el-divider>
        <el-steps :active="currentStepIndex" finish-status="success" align-center>
          <el-step v-for="step in STEP_TIMELINE" :key="step.key" :title="step.label" :description="step.desc" />
        </el-steps>

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
  </div>
</template>

<script lang="ts">
/**
 * TestRun.vue — 测试任务创建 + 列表 + 详情
 *
 * P0 重构：3 模式入口
 * - auto：  拉 GitHub/SVN 代码 → 解析 → AI 生成 → 执行（向后兼容）
 * - plan：  选择已建测试计划 → 跳过 fetch/analyze/AI 生成 → 直接执行计划内用例
 * - upload：上传 zip/tar.gz → 解析 → AI 生成 → 执行（auto 的特例，独立 UI）
 *
 * 实现注意：本文件用 Options API（defineComponent）实现，
 * 因为 vue-tsc 4.x 对 script setup 大块 const 头部有 bug（Property 'X' does not exist on type `{}`）。
 * Options API 的 data() 返回类型显式，规避该 bug。
 */
import { defineComponent } from 'vue'
import { Plus, VideoPlay, UploadFilled } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { UploadRequestOptions } from 'element-plus'
import { projectApi, testRunApi, uploadApi, planApi } from '@/api'

const STATUS_OPTIONS: Record<string, string> = {
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

const STEP_TIMELINE = [
  { key: 'pending', label: '准备', desc: '任务排队' },
  { key: 'pulling', label: '拉取代码', desc: '从仓库下载' },
  { key: 'analyzing', label: '解析', desc: '识别技术栈' },
  { key: 'generating', label: '生成用例', desc: 'AI 生成测试用例' },
  { key: 'executing', label: '执行', desc: '跑测试用例' },
  { key: 'analyzing_defects', label: '缺陷分析', desc: 'AI 分析失败' },
  { key: 'reporting', label: '报告', desc: '生成测试报告' },
  { key: 'completed', label: '完成', desc: '结果归档' },
]

const STATUS_TAG: Record<string, string> = {
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

export default defineComponent({
  name: 'TestRunView',
  components: { Plus, VideoPlay, UploadFilled },
  data() {
    return {
      activeMode: 'auto' as 'auto' | 'plan' | 'upload',
      loading: false,
      creating: false,
      plansLoading: false,

      testRuns: [] as any[],
      projects: [] as any[],
      plans: [] as any[],

      detailVisible: false,
      selectedRun: null as any,
      detailProgress: 0,
      detailStep: '',
      progressTimer: null as number | null,

      filterProjectId: '',
      filterMode: '' as '' | 'auto' | 'plan' | 'upload',
      filterStatus: '',

      selectedPlanId: '' as string,

      form: {
        source_type: 'github',
        repo_url: '',
        github_token: '',
        branch: 'main',
        svn_url: '',
        svn_username: '',
        svn_password: '',
        upload_file_path: '',
        project_id: '' as string,
      },

      STATUS_OPTIONS,
      STEP_TIMELINE,
    }
  },
  computed: {
    selectedPlan(): any {
      return this.plans.find((p: any) => p.id === this.selectedPlanId) || null
    },
    currentStepIndex(): number {
      const step = this.detailStep || this.selectedRun?.current_step || this.selectedRun?.status || 'pending'
      const idx = this.STEP_TIMELINE.findIndex((s) => s.key === step)
      return idx === -1 ? 0 : idx
    },
  },
  watch: {
    activeMode(mode: string): void {
      if (mode === 'plan' && this.plans.length === 0 && !this.plansLoading) {
        this.loadPlans()
      }
    },
  },
  methods: {
    // ============ 数据加载 ============
    async loadProjects(): Promise<void> {
      try {
        const res: any = await projectApi.getList()
        const d = res?.data ?? res
        this.projects = Array.isArray(d) ? d : d?.list || d?.items || []
      } catch {
        this.projects = []
      }
    },
    async loadPlans(): Promise<void> {
      this.plansLoading = true
      try {
        const res: any = await planApi.list({ page: 1, page_size: 200 })
        const list = res?.data?.list || res?.data?.items || res?.list || []
        this.plans = Array.isArray(list) ? list : []
      } catch {
        this.plans = []
      } finally {
        this.plansLoading = false
      }
    },
    async loadTestRuns(): Promise<void> {
      this.loading = true
      try {
        const params: any = {}
        if (this.filterProjectId) params.project_id = this.filterProjectId
        if (this.filterStatus) params.status = this.filterStatus
        const res: any = await testRunApi.getList(params)
        let list: any[] = res?.data?.list || []
        if (this.filterMode === 'plan') {
          list = list.filter((r) => !!r.plan_id)
        } else if (this.filterMode === 'auto' || this.filterMode === 'upload') {
          list = list.filter((r) => !r.plan_id)
        }
        this.testRuns = list

        const hasInProgress = this.testRuns.some(
          (r) => !['completed', 'failed', 'cancelled'].includes(r.status),
        )
        if (hasInProgress) this.schedulePoll()
      } catch {
        this.testRuns = []
      } finally {
        this.loading = false
      }
    },

    schedulePoll(): void {
      if (this.progressTimer) return
      this.progressTimer = window.setInterval(() => {
        this.loadTestRuns()
        if (this.detailVisible && this.selectedRun) {
          this.updateDetailProgress(this.selectedRun.id)
        }
        const stillInProgress = this.testRuns.some(
          (r) => !['completed', 'failed', 'cancelled'].includes(r.status),
        )
        if (!stillInProgress && this.progressTimer) {
          clearInterval(this.progressTimer)
          this.progressTimer = null
        }
      }, 3000)
    },

    async updateDetailProgress(runId: string): Promise<void> {
      try {
        const res: any = await testRunApi.getProgress(runId)
        const data = res?.data
        if (data) {
          this.detailProgress = data.progress || 0
          this.detailStep = data.step || ''
        }
      } catch {
        /* polling 错误忽略 */
      }
    },

    handleRowClick(row: any): void {
      this.selectedRun = row
      this.detailProgress = row.progress || 0
      this.detailStep = ''
      this.detailVisible = true
      if (!['completed', 'failed', 'cancelled'].includes(row.status)) {
        this.updateDetailProgress(row.id)
        this.schedulePoll()
      }
    },

    // ============ 创建测试任务：auto 模式 ============
    resetForm(): void {
      this.form.source_type = 'github'
      this.form.repo_url = ''
      this.form.github_token = ''
      this.form.branch = 'main'
      this.form.svn_url = ''
      this.form.svn_username = ''
      this.form.svn_password = ''
      this.form.upload_file_path = ''
      this.form.project_id = ''
    },
    async handleCreateAuto(): Promise<void> {
      if (this.form.source_type === 'github' && !this.form.repo_url) {
        ElMessage.warning('请输入仓库 URL')
        return
      }
      if (this.form.source_type === 'svn' && !this.form.svn_url) {
        ElMessage.warning('请输入 SVN URL')
        return
      }
      this.creating = true
      try {
        await testRunApi.create({
          mode: 'auto',
          source_type: this.form.source_type,
          repo_url: this.form.repo_url,
          github_token: this.form.github_token || undefined,
          branch: this.form.branch,
          svn_url: this.form.svn_url,
          svn_username: this.form.svn_username,
          svn_password: this.form.svn_password,
          project_id: this.form.project_id || undefined,
        })
        ElMessage.success('测试已在后台启动，可在列表中查看实时进度')
        this.resetForm()
        this.loadTestRuns()
      } catch {
        /* axios 拦截器已处理 */
      } finally {
        this.creating = false
      }
    },

    // ============ 创建测试任务：upload 模式 ============
    async handleCreateUpload(): Promise<void> {
      if (!this.form.upload_file_path) {
        ElMessage.warning('请先上传代码文件')
        return
      }
      this.creating = true
      try {
        await testRunApi.create({
          mode: 'upload',
          source_type: 'upload',
          upload_file_path: this.form.upload_file_path,
          project_id: this.form.project_id || undefined,
        })
        ElMessage.success('测试已在后台启动，可在列表中查看实时进度')
        this.resetForm()
        this.loadTestRuns()
      } catch {
        /* axios 拦截器已处理 */
      } finally {
        this.creating = false
      }
    },

    // ============ 创建测试任务：plan 模式 ============
    async handleExecutePlan(): Promise<void> {
      if (!this.selectedPlanId) {
        ElMessage.warning('请先选择测试计划')
        return
      }
      this.creating = true
      try {
        // 直接调 planApi.execute：后端会在内部创建 TestRun 并触发 pipeline（mode=plan）
        const res: any = await planApi.execute(this.selectedPlanId)
        ElMessage.success('测试计划已启动，可在列表中查看实时进度')
        this.selectedPlanId = ''
        this.loadTestRuns()
        if (res?.data?.test_run_id) {
          this.activeMode = 'auto'
        }
      } catch {
        /* axios 拦截器已处理 */
      } finally {
        this.creating = false
      }
    },

    async handleUpload(options: UploadRequestOptions): Promise<void> {
      try {
        const res: any = await uploadApi.upload(options.file as File)
        this.form.upload_file_path = res?.data?.upload_file_path || ''
        if (!this.form.upload_file_path) {
          ElMessage.error('上传响应缺少压缩包路径，请重试或联系管理员')
          return
        }
        ElMessage.success('文件上传成功')
      } catch {
        /* axios 拦截器已处理 */
      }
    },

    async handleCancel(row: any): Promise<void> {
      try {
        await ElMessageBox.confirm(`确定要取消任务「${row.id.substring(0, 8)}」吗？`, '确认取消', { type: 'warning' })
        await testRunApi.cancel(row.id)
        ElMessage.success('任务已取消')
        this.loadTestRuns()
      } catch {
        /* 用户取消 */
      }
    },

    // ============ UI helpers ============
    statusTagType(status: string): string {
      return STATUS_TAG[status] || 'info'
    },
    statusLabel(status: string): string {
      return STATUS_OPTIONS[status] || status
    },
    progressStatus(status: string): string {
      if (status === 'completed') return 'success'
      if (status === 'failed') return 'exception'
      return ''
    },
    formatTime(time: string): string {
      if (!time) return ''
      try {
        return new Date(time).toLocaleString('zh-CN')
      } catch {
        return time
      }
    },
  },
  mounted() {
    this.loadProjects()
    this.loadTestRuns()
  },
  beforeUnmount() {
    if (this.progressTimer) {
      clearInterval(this.progressTimer)
      this.progressTimer = null
    }
  },
})
</script>

<style scoped>
.create-card {
  margin-bottom: 16px;
}
.list-card {
  margin-top: 0;
}
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.mode-tabs :deep(.el-tabs__header) {
  margin-bottom: 16px;
}
.mode-desc {
  color: #909399;
  font-size: 13px;
  line-height: 1.8;
  margin-bottom: 16px;
}
.mode-desc b {
  color: #409eff;
}
.plan-select-row {
  display: flex;
  gap: 8px;
  width: 100%;
}
.plan-select {
  flex: 1;
}
.form-actions {
  margin-top: 8px;
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
.mono-text {
  font-family: 'Courier New', Consolas, monospace;
  font-size: 13px;
  color: #606266;
  word-break: break-all;
}
.source-text {
  font-size: 12px;
}
.step-text {
  font-size: 13px;
  color: #303133;
}
.time-text {
  font-size: 12px;
  color: #606266;
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