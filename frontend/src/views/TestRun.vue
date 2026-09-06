<template>
  <div class="test-run-page">
    <!-- 执行测试计划（代码进入与执行统一走项目管理） -->
    <el-card shadow="hover" class="create-card">
      <template #header>
        <div class="card-header">
          <span>执行测试计划</span>
        </div>
      </template>

        <!-- 测试计划执行（唯一创建入口；代码经项目版本化后由版本触发执行） -->
          <div class="mode-desc">
            按计划执行：跳过代码拉取与 AI 生成，直接运行计划内已启用的用例，适合回归测试。
            <br>
            还没有计划？到<b>「用例库」</b>选择用例 → 点<b>「加入计划」</b>→ 选「新建计划」即可创建。
            <br>
            要测试<b>新代码</b>？到<b>「项目管理」</b>项目详情上传/拉取代码版本 → 点<b>「执行测试」</b>。
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
                <el-button :disabled="!selectedPlanId" @click="openPlanDrawer">管理计划</el-button>
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

    <!-- R2：计划管理抽屉 —— 用例清单 / 启停 / 移除 / 执行历史 -->
    <el-drawer v-model="planDrawerVisible" :title="`管理计划 - ${planDetail?.name || ''}`" size="680px">
      <div v-if="planDetail" class="plan-drawer-body">
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="所属项目">{{ planDetail.project_name || '—' }}</el-descriptions-item>
          <el-descriptions-item label="状态">
            <el-tag size="small" :type="planDetail.status === 'active' ? 'success' : 'info'">
              {{ planDetail.status === 'active' ? '启用中' : '已归档' }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="描述" :span="2">{{ planDetail.description || '—' }}</el-descriptions-item>
        </el-descriptions>

        <div class="plan-section-header">
          <span>计划用例（{{ planCases.length }}）</span>
          <el-button size="small" plain @click="goCaseLibrary">去用例库添加</el-button>
        </div>
        <el-table :data="planCases" v-loading="planCasesLoading" stripe size="small" max-height="320">
          <el-table-column label="用例标题" min-width="200" show-overflow-tooltip>
            <template #default="{ row }">{{ row.case?.title || '（用例已被删除）' }}</template>
          </el-table-column>
          <el-table-column label="类型" width="90" align="center">
            <template #default="{ row }">
              <el-tag size="small" effect="plain">{{ caseTypeLabel(row.case?.case_type) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="优先级" width="80" align="center">
            <template #default="{ row }">{{ row.case?.priority || '—' }}</template>
          </el-table-column>
          <el-table-column label="启用" width="80" align="center">
            <template #default="{ row }">
              <el-switch :model-value="row.enabled" @change="onToggleCase(row, $event as boolean)" />
            </template>
          </el-table-column>
          <el-table-column label="操作" width="80" fixed="right">
            <template #default="{ row }">
              <el-button size="small" type="danger" plain @click="onRemoveCase(row)">移除</el-button>
            </template>
          </el-table-column>
        </el-table>

        <div class="plan-section-header">
          <span>执行历史（{{ planExecs.length }}）</span>
          <div>
            <el-button size="small" plain @click="$router.push('/scheduled-tasks')">定时回归</el-button>
            <el-button size="small" :loading="planExecsLoading" @click="loadPlanExecs">刷新</el-button>
          </div>
        </div>
        <el-table :data="planExecs" v-loading="planExecsLoading" stripe size="small" max-height="280">
          <el-table-column label="时间" width="160">
            <template #default="{ row }">
              <span class="time-text">{{ formatTime(row.started_at) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="90" align="center">
            <template #default="{ row }">
              <el-tag size="small" :type="statusTagType(row.status)">{{ statusLabel(row.status) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="通过/失败/总数" width="130" align="center">
            <template #default="{ row }">
              <span :style="{ color: row.failed > 0 ? '#f56c6c' : '#67c23a' }">
                {{ row.passed }}/{{ row.failed }}/{{ row.total }}
              </span>
            </template>
          </el-table-column>
          <el-table-column label="任务 ID" min-width="120">
            <template #default="{ row }">
              <span class="mono-text">{{ row.test_run_id?.substring(0, 8) }}</span>
            </template>
          </el-table-column>
        </el-table>
        <el-empty
          v-if="!planExecsLoading && planExecs.length === 0"
          description="该计划还没有执行记录 —— 回到上方点「执行计划」"
          :image-size="72"
        />
      </div>
    </el-drawer>
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
import { VideoPlay } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { projectApi, testRunApi, planApi } from '@/api'

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
  components: { VideoPlay },
  data() {
    return {
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

      // R2：计划管理抽屉
      planDrawerVisible: false,
      planDetail: null as any,
      planCases: [] as any[],
      planCasesLoading: false,
      planExecs: [] as any[],
      planExecsLoading: false,

      selectedPlanId: '' as string,


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

    // ============ R2：计划管理抽屉 ============
    caseTypeLabel(t?: string): string {
      const map: Record<string, string> = {
        api: '接口',
        scenario: '场景',
        integration: '集成',
        performance: '性能',
      }
      return map[t || ''] || t || '—'
    },
    async openPlanDrawer(): Promise<void> {
      if (!this.selectedPlanId) return
      this.planDrawerVisible = true
      this.planDetail = this.plans.find((p: any) => p.id === this.selectedPlanId) || null
      this.loadPlanDetail()
      this.loadPlanExecs()
    },
    async loadPlanDetail(): Promise<void> {
      if (!this.selectedPlanId) return
      this.planCasesLoading = true
      try {
        const res: any = await planApi.get(this.selectedPlanId)
        this.planDetail = res?.data || null
        this.planCases = res?.data?.cases || []
      } catch {
        this.planCases = []
      } finally {
        this.planCasesLoading = false
      }
    },
    async loadPlanExecs(): Promise<void> {
      if (!this.selectedPlanId) return
      this.planExecsLoading = true
      try {
        const res: any = await planApi.listExecutions(this.selectedPlanId, { page: 1, page_size: 50 })
        this.planExecs = res?.data?.list || []
      } catch {
        this.planExecs = []
      } finally {
        this.planExecsLoading = false
      }
    },
    async onToggleCase(row: any, enabled: boolean): Promise<void> {
      try {
        await planApi.toggleCase(this.selectedPlanId, row.case_asset_id, enabled)
        row.enabled = enabled
        ElMessage.success(enabled ? '用例已启用，下次执行将包含' : '用例已停用，下次执行将跳过')
        this.loadPlans()
      } catch {
        /* 拦截器已提示 */
      }
    },
    async onRemoveCase(row: any): Promise<void> {
      const title = row.case?.title || row.case_asset_id?.substring(0, 8)
      try {
        await ElMessageBox.confirm(`确定从计划中移除用例「${title}」吗？`, '移除确认', { type: 'warning' })
      } catch {
        return
      }
      try {
        await planApi.removeCase(this.selectedPlanId, row.case_asset_id)
        ElMessage.success('已从计划移除')
        this.loadPlanDetail()
        this.loadPlans()
      } catch {
        /* 拦截器已提示 */
      }
    },
    goCaseLibrary(): void {
      const pid = this.planDetail?.project_id || ''
      window.location.href = pid ? `/case-library?project_id=${pid}` : '/case-library'
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
      } catch {
        /* axios 拦截器已处理 */
      } finally {
        this.creating = false
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
.plan-drawer-body {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.plan-section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 6px;
  font-weight: 600;
  color: #303133;
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