<template>
  <div class="coverage-dashboard">
    <!-- 顶部：项目 + 报告选择 -->
    <el-card shadow="hover" class="filter-card">
      <div class="filter-row">
        <div class="filter-item">
          <span class="label">项目</span>
          <el-select
            v-model="projectId"
            placeholder="选择项目"
            filterable
            clearable
            style="width: 280px"
            @change="onProjectChange"
          >
            <el-option v-for="p in projects" :key="p.id" :label="p.name" :value="p.id" />
          </el-select>
        </div>
        <div class="filter-item">
          <span class="label">报告</span>
          <el-select
            v-model="selectedReportId"
            placeholder="选择覆盖率报告"
            filterable
            clearable
            :loading="loadingReports"
            :disabled="!projectId"
            style="width: 380px"
            @change="onReportChange"
          >
            <el-option
              v-for="r in reports"
              :key="r.id"
              :label="reportLabel(r)"
              :value="r.id"
            />
          </el-select>
        </div>
        <el-tooltip content="开启后流水线测试会自动采集本项目覆盖率（平台总开关需为开启）" placement="top">
          <div class="cov-switch">
            <span class="cov-switch-label">自动采集</span>
            <el-switch
              v-model="autoCoverage"
              :loading="covSwitchLoading"
              :disabled="!projectId || !canManage"
              @change="onAutoCoverageChange"
            />
          </div>
        </el-tooltip>
        <el-button :disabled="!projectId" @click="refreshAll">刷新</el-button>
        <el-button type="primary" :icon="UploadFilled" :disabled="!projectId" @click="openUploadDialog">上传报告</el-button>
      </div>
    </el-card>

    <template v-if="!projectId">
      <el-empty description="请先选择项目" />
    </template>

    <template v-else-if="!latestReportId && reports.length === 0 && !loadingReports">
      <el-card shadow="hover" class="empty-card">
        <el-empty description="该项目暂无覆盖率报告">
          <el-button type="primary" :icon="UploadFilled" @click="openUploadDialog">上传覆盖率报告</el-button>
          <div class="empty-tip">
            支持 coverage.py / JaCoCo / istanbul / Cobertura 格式的 XML 报告
          </div>
        </el-empty>
      </el-card>
    </template>

    <template v-else>
      <!-- 4 张指标卡 -->
      <el-row :gutter="16" class="metric-row">
        <el-col :xs="12" :sm="6">
          <el-card shadow="hover" class="metric-card">
            <div class="metric-label">行覆盖率</div>
            <div class="metric-value" :class="rateClass(dashboard?.latest?.line_rate)">
              {{ fmt(dashboard?.latest?.line_rate) }}<span class="metric-unit">%</span>
            </div>
            <div class="metric-diff" v-if="dashboard?.diff_line_rate != null">
              <el-tag
                :type="dashboard.diff_line_rate > 0 ? 'success' : dashboard.diff_line_rate < 0 ? 'danger' : 'info'"
                size="small"
                effect="plain"
              >
                {{ dashboard.diff_line_rate > 0 ? '▲' : dashboard.diff_line_rate < 0 ? '▼' : '—' }}
                {{ Math.abs(dashboard.diff_line_rate).toFixed(2) }}
              </el-tag>
              <span class="metric-diff-label">较上次</span>
            </div>
          </el-card>
        </el-col>
        <el-col :xs="12" :sm="6">
          <el-card shadow="hover" class="metric-card">
            <div class="metric-label">分支覆盖率</div>
            <div class="metric-value" :class="rateClass(dashboard?.latest?.branch_rate)">
              {{ fmt(dashboard?.latest?.branch_rate) }}<span class="metric-unit">%</span>
            </div>
            <div class="metric-diff" v-if="dashboard?.diff_branch_rate != null">
              <el-tag
                :type="dashboard.diff_branch_rate > 0 ? 'success' : dashboard.diff_branch_rate < 0 ? 'danger' : 'info'"
                size="small"
                effect="plain"
              >
                {{ dashboard.diff_branch_rate > 0 ? '▲' : dashboard.diff_branch_rate < 0 ? '▼' : '—' }}
                {{ Math.abs(dashboard.diff_branch_rate).toFixed(2) }}
              </el-tag>
              <span class="metric-diff-label">较上次</span>
            </div>
          </el-card>
        </el-col>
        <el-col :xs="12" :sm="6">
          <el-card shadow="hover" class="metric-card">
            <div class="metric-label">已覆盖行 / 总行</div>
            <div class="metric-value neutral">
              {{ dashboard?.latest?.covered_lines ?? 0 }}
              <span class="metric-unit-sm">/ {{ dashboard?.latest?.total_lines ?? 0 }}</span>
            </div>
            <div class="metric-diff">
              <span class="metric-diff-label">覆盖分支 {{ dashboard?.latest?.covered_branches ?? 0 }} / {{ dashboard?.latest?.total_branches ?? 0 }}</span>
            </div>
          </el-card>
        </el-col>
        <el-col :xs="12" :sm="6">
          <el-card shadow="hover" class="metric-card">
            <div class="metric-label">报告 / 文件</div>
            <div class="metric-value neutral">
              {{ dashboard?.report_count ?? 0 }}
              <span class="metric-unit-sm">/ {{ dashboard?.file_count ?? 0 }}</span>
            </div>
            <div class="metric-diff">
              <span class="metric-diff-label">项目内累计</span>
            </div>
          </el-card>
        </el-col>
      </el-row>

      <!-- 趋势图 -->
      <el-card shadow="hover" class="trend-card">
        <template #header>
          <span>覆盖率趋势（最近 30 天）</span>
        </template>
        <TrendChart
          v-if="trend.labels && trend.labels.length"
          :labels="trend.labels"
          :series="trendSeries"
          :height="240"
          y-axis-name="%"
        />
        <el-empty v-else description="近 30 天暂无报告" :image-size="80" />
      </el-card>

      <!-- 文件表 -->
      <el-card shadow="hover" class="files-card">
        <template #header>
          <div class="files-header">
            <span>文件级明细（共 {{ filesTotal }} 个文件）</span>
            <div class="files-tools">
              <el-input
                v-model="fileQuery"
                placeholder="搜索文件路径"
                clearable
                size="small"
                style="width: 240px"
                @input="onFileQueryChange"
              />
              <el-select
                v-model="fileSort"
                size="small"
                style="width: 120px"
                @change="onFileSortChange"
              >
                <el-option label="按行率" value="rate" />
                <el-option label="按路径" value="path" />
                <el-option label="按总行" value="total_lines" />
              </el-select>
              <el-select
                v-model="fileOrder"
                size="small"
                style="width: 90px"
                @change="onFileSortChange"
              >
                <el-option label="升序" value="asc" />
                <el-option label="降序" value="desc" />
              </el-select>
            </div>
          </div>
        </template>
        <el-table
          v-loading="loadingFiles"
          :data="files"
          size="small"
          border
          stripe
          empty-text="该报告无文件明细"
          @row-click="onFileRowClick"
        >
          <el-table-column prop="path" label="文件路径" min-width="280" show-overflow-tooltip>
            <template #default="{ row }">
              <span class="file-path">{{ row.path }}</span>
            </template>
          </el-table-column>
          <el-table-column label="行覆盖" width="200" align="center">
            <template #default="{ row }">
              <el-progress
                :percentage="fmt(row.line_rate)"
                :color="progressColor(row.line_rate)"
                :stroke-width="10"
                :show-text="false"
                style="width: 110px; display: inline-block; vertical-align: middle; margin-right: 8px"
              />
              <span :class="rateClass(row.line_rate)">{{ fmt(row.line_rate) }}%</span>
            </template>
          </el-table-column>
          <el-table-column label="分支覆盖" width="120" align="center">
            <template #default="{ row }">
              <span v-if="row.branch_rate == null" class="text-muted">-</span>
              <span v-else :class="rateClass(row.branch_rate)">{{ fmt(row.branch_rate) }}%</span>
            </template>
          </el-table-column>
          <el-table-column label="覆盖行" width="100" align="center">
            <template #default="{ row }">
              {{ row.covered_lines }}/{{ row.total_lines }}
            </template>
          </el-table-column>
          <el-table-column label="操作" width="80" fixed="right">
            <template #default="{ row }">
              <el-button size="small" text type="primary" @click.stop="onFileRowClick(row)">查看行</el-button>
            </template>
          </el-table-column>
        </el-table>
        <el-pagination
          v-if="filesTotal > pageSize"
          class="files-pagination"
          :current-page="page"
          :page-size="pageSize"
          :total="filesTotal"
          :page-sizes="[20, 50, 100, 200]"
          layout="total, sizes, prev, pager, next, jumper"
          @current-change="onPageChange"
          @size-change="onPageSizeChange"
        />
      </el-card>
    </template>

    <!-- 源码行级覆盖 抽屉 -->
    <el-drawer
      v-model="drawerOpen"
      :title="drawerTitle"
      direction="rtl"
      size="640px"
      destroy-on-close
    >
      <div v-loading="loadingSource" class="source-drawer-body">
        <div v-if="sourceData" class="source-summary">
          <el-tag :type="rateType(sourceData.line_rate)" effect="plain" size="large">
            行覆盖 {{ fmt(sourceData.line_rate) }}%
          </el-tag>
          <el-tag
            v-if="sourceData.branch_rate != null"
            :type="rateType(sourceData.branch_rate)"
            effect="plain"
            size="large"
            style="margin-left: 8px"
          >
            分支覆盖 {{ fmt(sourceData.branch_rate) }}%
          </el-tag>
          <el-tag effect="plain" size="large" style="margin-left: 8px">
            {{ sourceData.covered_lines }} / {{ sourceData.total_lines }} 行
          </el-tag>
        </div>
        <div v-if="sourceData" class="legend">
          <span class="legend-item"><span class="dot covered"></span>已覆盖</span>
          <span class="legend-item"><span class="dot partial"></span>分支部分覆盖</span>
          <span class="legend-item"><span class="dot uncovered"></span>未覆盖</span>
        </div>
        <div v-if="sourceData" class="source-line-list">
          <div
            v-for="line in sourceData.lines"
            :key="line.number"
            class="source-line"
            :class="lineClass(line)"
          >
            <span class="line-no">{{ line.number }}</span>
            <span class="line-icon">{{ lineIcon(line) }}</span>
            <span class="line-hits">hits={{ line.hits }}</span>
            <span v-if="line.total_branches > 0" class="line-branch">
              分支 {{ line.covered_branches }}/{{ line.total_branches }}
            </span>
          </div>
          <el-empty v-if="!sourceData.lines.length" description="该文件无行级数据" />
        </div>
      </div>
    </el-drawer>

    <!-- 上传覆盖率报告 对话框 -->
    <el-dialog
      v-model="uploadDialogVisible"
      title="上传覆盖率报告"
      width="560px"
      :close-on-click-modal="false"
      destroy-on-close
    >
      <el-form label-width="100px" :model="uploadForm">
        <el-form-item label="工具" required>
          <el-select v-model="uploadForm.tool" style="width: 100%">
            <el-option label="coverage.py (Python)" value="coverage.py" />
            <el-option label="JaCoCo (Java)" value="jacoco" />
            <el-option label="istanbul / nyc (Node)" value="istanbul" />
            <el-option label="Cobertura (通用)" value="cobertura" />
          </el-select>
        </el-form-item>
        <el-form-item label="语言">
          <el-input v-model="uploadForm.language" placeholder="可选：python / java / javascript" />
        </el-form-item>
        <el-form-item label="XML 报告" required>
          <el-upload
            :auto-upload="false"
            :limit="1"
            :show-file-list="true"
            accept=".xml"
            :on-change="onUploadFileChange"
            :on-exceed="() => ElMessage.warning('每次仅可上传一个文件')"
          >
            <el-button :icon="UploadFilled">选择文件</el-button>
            <template #tip>
              <div class="el-upload__tip">
                coverage.py 执行 <code>coverage xml</code>、JaCoCo 执行 <code>jacoco:report</code> 生成 XML 后上传（≤ 20MB）
              </div>
            </template>
          </el-upload>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="uploadDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="uploading" :disabled="!uploadForm.file" @click="submitUpload">
          解析并入库
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { UploadFilled } from '@element-plus/icons-vue'
import { coverageApi, projectApi, projectConfigApi } from '@/api'
import { useAuthStore } from '@/stores'
import TrendChart from '@/components/TrendChart.vue'

// ====== 状态 ======
const projects = ref<any[]>([])
const projectId = ref<string>('')
const authStore = useAuthStore()
const canManage = computed(() =>
  ['super_admin', 'admin', 'test_manager'].includes(authStore.role)
)
const autoCoverage = ref<boolean>(true)
watch(projectId, () => void loadCoverageSwitch())
const covSwitchLoading = ref<boolean>(false)

async function loadCoverageSwitch(): Promise<void> {
  if (!projectId.value) return
  try {
    const res: any = await projectConfigApi.getCIConfig(projectId.value)
    if (res?.code === 0 && res?.data) {
      autoCoverage.value = res.data.auto_coverage !== false
    }
  } catch { /* 忽略，保持默认 */ }
}

async function onAutoCoverageChange(val: boolean): Promise<void> {
  try {
    covSwitchLoading.value = true
    const res: any = await projectConfigApi.setCoverageConfig(projectId.value, val)
    if (res?.code === 0) {
      ElMessage.success(val ? '已开启本项目自动覆盖率采集' : '已关闭本项目自动覆盖率采集')
    } else {
      autoCoverage.value = !val
      ElMessage.error(res?.message || '设置失败')
    }
  } catch {
    autoCoverage.value = !val
  } finally {
    covSwitchLoading.value = false
  }
}
const reports = ref<any[]>([])
const selectedReportId = ref<string>('')
const latestReportId = ref<string>('')  // 看板数据绑定的报告（默认最新一份）
const loadingReports = ref(false)

const dashboard = ref<any>(null)
const trend = ref<any>({ labels: [], line_rate: [], branch_rate: [] })
const trendSeries = computed(() => [
  { name: '行覆盖率', data: trend.value.line_rate || [], color: '#67c23a' },
  { name: '分支覆盖率', data: trend.value.branch_rate || [], color: '#409eff' },
])

const files = ref<any[]>([])
const filesTotal = ref(0)
const loadingFiles = ref(false)
const fileQuery = ref('')
const fileSort = ref<'rate' | 'path' | 'total_lines'>('rate')
const fileOrder = ref<'asc' | 'desc'>('asc')
const page = ref(1)
const pageSize = ref(50)

// 源码抽屉
const drawerOpen = ref(false)
const drawerTitle = ref('')
const sourceData = ref<any>(null)
const loadingSource = ref(false)

// 上传对话框
const uploadDialogVisible = ref(false)
const uploading = ref(false)
const uploadForm = ref<{
  tool: string
  language: string
  file: File | null
}>({
  tool: 'coverage.py',
  language: '',
  file: null,
})

// ====== 工具 ======
function fmt(v: any): string {
  if (v == null) return '0'
  return Number(v).toFixed(1)
}
function rateType(rate: number | null | undefined): any {
  const r = Number(rate || 0)
  if (r >= 80) return 'success'
  if (r >= 60) return 'warning'
  return 'danger'
}
function rateClass(rate: number | null | undefined): string {
  const r = Number(rate || 0)
  if (r >= 80) return 'rate-good'
  if (r >= 60) return 'rate-mid'
  return 'rate-bad'
}
function progressColor(rate: number | null | undefined): string {
  const r = Number(rate || 0)
  if (r >= 80) return '#67c23a'
  if (r >= 60) return '#e6a23c'
  return '#f56c6c'
}
function reportLabel(r: any): string {
  const date = (r.created_at || '').slice(0, 16).replace('T', ' ')
  return `${date} · ${r.tool} · 行 ${r.line_rate}% / 分支 ${r.branch_rate}% · ${r.covered_lines}/${r.total_lines} 行`
}
function lineClass(line: any): string {
  if (line.hits > 0 && line.total_branches > 0 && line.covered_branches < line.total_branches) {
    return 'line-partial'
  }
  if (line.hits > 0) return 'line-covered'
  return 'line-uncovered'
}
function lineIcon(line: any): string {
  if (line.hits > 0 && line.total_branches > 0 && line.covered_branches < line.total_branches) return '◐'
  if (line.hits > 0) return '●'
  return '○'
}

// ====== 加载 ======
async function loadProjects() {
  try {
    const res: any = await projectApi.getList()
    const d = res?.data ?? res
    projects.value = Array.isArray(d) ? d : d?.list || d?.items || []
  } catch (e: any) {
    projects.value = []
    ElMessage.error('加载项目列表失败：' + (e?.message || '请检查后端 /api/projects'))
  }
}

async function loadReports() {
  if (!projectId.value) return
  loadingReports.value = true
  try {
    const res: any = await coverageApi.list({ project_id: projectId.value })
    const list = res?.data || []
    reports.value = Array.isArray(list) ? list : []
    if (reports.value.length && !selectedReportId.value) {
      selectedReportId.value = reports.value[0].id
      latestReportId.value = reports.value[0].id
    } else if (!reports.value.length) {
      selectedReportId.value = ''
      latestReportId.value = ''
    }
  } catch {
    reports.value = []
  } finally {
    loadingReports.value = false
  }
}

async function loadDashboard() {
  if (!projectId.value) return
  try {
    const res: any = await coverageApi.dashboard(projectId.value)
    dashboard.value = res?.data || null
  } catch {
    dashboard.value = null
  }
}

async function loadTrend() {
  if (!projectId.value) return
  try {
    const res: any = await coverageApi.trend(projectId.value, 30)
    trend.value = res?.data || { labels: [], line_rate: [], branch_rate: [] }
  } catch {
    trend.value = { labels: [], line_rate: [], branch_rate: [] }
  }
}

async function loadFiles() {
  if (!latestReportId.value) return
  loadingFiles.value = true
  try {
    const res: any = await coverageApi.files(latestReportId.value, {
      sort: fileSort.value,
      order: fileOrder.value,
      page: page.value,
      page_size: pageSize.value,
      q: fileQuery.value || undefined,
    })
    const d = res?.data || {}
    files.value = d.files || []
    filesTotal.value = d.total || 0
  } catch {
    files.value = []
    filesTotal.value = 0
  } finally {
    loadingFiles.value = false
  }
}

async function onFileRowClick(row: any) {
  if (!latestReportId.value) return
  drawerTitle.value = row.path
  drawerOpen.value = true
  loadingSource.value = true
  try {
    const res: any = await coverageApi.source(latestReportId.value, row.path)
    sourceData.value = res?.data || null
  } catch (e: any) {
    sourceData.value = null
    ElMessage.error('加载行级数据失败：' + (e?.message || '未知错误'))
  } finally {
    loadingSource.value = false
  }
}

async function onProjectChange() {
  selectedReportId.value = ''
  latestReportId.value = ''
  files.value = []
  filesTotal.value = 0
  dashboard.value = null
  trend.value = { labels: [], line_rate: [], branch_rate: [] }
  await loadReports()
  await loadDashboard()
  await loadTrend()
  await loadFiles()
}

async function onReportChange() {
  latestReportId.value = selectedReportId.value
  page.value = 1
  await loadFiles()
}

async function refreshAll() {
  await loadReports()
  await loadDashboard()
  await loadTrend()
  await loadFiles()
}

function openUploadDialog() {
  if (!projectId.value) {
    ElMessage.warning('请先选择项目')
    return
  }
  uploadForm.value = { tool: 'coverage.py', language: '', file: null }
  uploadDialogVisible.value = true
}

function onUploadFileChange(file: any) {
  // el-upload 的 file 对象在 raw
  uploadForm.value.file = file?.raw || null
}

async function submitUpload() {
  if (!uploadForm.value.file || !uploadForm.value.tool) {
    ElMessage.warning('请选择工具和 XML 文件')
    return
  }
  uploading.value = true
  try {
    const res: any = await coverageApi.upload(uploadForm.value.file, {
      project_id: projectId.value,
      tool: uploadForm.value.tool,
      language: uploadForm.value.language || undefined,
    })
    const d = res?.data || {}
    ElMessage.success(
      `已入库：行覆盖 ${d.line_rate}% / 分支 ${d.branch_rate}%（${d.file_count} 个文件）`
    )
    uploadDialogVisible.value = false
    await refreshAll()
  } catch {
    /* 拦截器已提示 */
  } finally {
    uploading.value = false
  }
}

function onFileQueryChange() {
  page.value = 1
  loadFiles()
}
function onFileSortChange() {
  page.value = 1
  loadFiles()
}
function onPageChange(p: number) {
  page.value = p
  loadFiles()
}
function onPageSizeChange(s: number) {
  pageSize.value = s
  page.value = 1
  loadFiles()
}

watch(projectId, (val) => {
  if (val) {
    onProjectChange()
  }
})

onMounted(() => {
  loadProjects()
})
</script>

<style scoped>
.coverage-dashboard {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.filter-card .filter-row {
  display: flex;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
}
.filter-item {
  display: flex;
  align-items: center;
  gap: 8px;
}
.filter-item .label {
  color: #606266;
  font-size: 13px;
  white-space: nowrap;
}

.metric-row {
  margin: 0;
}
.metric-card {
  text-align: center;
}
.metric-label {
  color: #909399;
  font-size: 13px;
  margin-bottom: 4px;
}
.metric-value {
  font-size: 28px;
  font-weight: 600;
  line-height: 1.2;
}
.metric-value.neutral {
  color: #303133;
}
.metric-unit {
  font-size: 14px;
  color: #909399;
  margin-left: 2px;
}
.metric-unit-sm {
  font-size: 14px;
  color: #909399;
  font-weight: normal;
}
.metric-diff {
  margin-top: 8px;
  font-size: 12px;
  color: #909399;
  display: flex;
  justify-content: center;
  align-items: center;
  gap: 4px;
}
.metric-diff-label {
  color: #909399;
}

.trend-card :deep(.el-card__body) {
  padding: 12px 16px;
}

.files-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}
.files-tools {
  display: flex;
  gap: 8px;
}
.file-path {
  font-family: 'Consolas', 'Monaco', monospace;
  font-size: 12px;
  color: #303133;
}
.rate-good {
  color: #67c23a;
  font-weight: 600;
}
.rate-mid {
  color: #e6a23c;
  font-weight: 600;
}
.rate-bad {
  color: #f56c6c;
  font-weight: 600;
}
.text-muted {
  color: #909399;
}
.files-pagination {
  margin-top: 12px;
  text-align: right;
}

/* 源码抽屉 */
.source-drawer-body {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.source-summary {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 4px;
}
.legend {
  display: flex;
  gap: 16px;
  font-size: 12px;
  color: #606266;
  padding: 4px 0;
  border-bottom: 1px solid #ebeef5;
}
.legend-item {
  display: flex;
  align-items: center;
  gap: 4px;
}
.dot {
  display: inline-block;
  width: 10px;
  height: 10px;
  border-radius: 50%;
}
.dot.covered {
  background: #67c23a;
}
.dot.partial {
  background: #e6a23c;
}
.dot.uncovered {
  background: #f56c6c;
}
.source-line-list {
  max-height: calc(100vh - 240px);
  overflow-y: auto;
  border: 1px solid #ebeef5;
  border-radius: 4px;
  background: #fafbfc;
  font-family: 'Consolas', 'Monaco', monospace;
  font-size: 12px;
}
.source-line {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 2px 12px;
  border-bottom: 1px solid #f0f2f5;
}
.source-line .line-no {
  width: 50px;
  text-align: right;
  color: #909399;
}
.source-line .line-icon {
  width: 16px;
  text-align: center;
  font-size: 14px;
}
.source-line .line-hits {
  color: #606266;
}
.source-line .line-branch {
  color: #909399;
  font-size: 11px;
}
.source-line.line-covered {
  background: #f0f9eb;
}
.source-line.line-covered .line-icon {
  color: #67c23a;
}
.source-line.line-uncovered {
  background: #fef0f0;
}
.source-line.line-uncovered .line-icon {
  color: #f56c6c;
}
.source-line.line-partial {
  background: #fdf6ec;
}
.source-line.line-partial .line-icon {
  color: #e6a23c;
}
.empty-card {
  padding: 8px;
}
.empty-tip {
  color: #909399;
  font-size: 12px;
  margin-top: 8px;
}
.cov-switch {
  display: flex;
  align-items: center;
  gap: 6px;
}
.cov-switch-label {
  font-size: 13px;
  color: #606266;
}
</style>
