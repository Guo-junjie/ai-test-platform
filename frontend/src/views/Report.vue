<template>
  <div class="report-page">
    <!-- Report list -->
    <el-card shadow="hover">
      <template #header>
        <div class="card-header">
          <span>测试报告</span>
          <div>
            <el-select
              v-model="filterProjectId"
              placeholder="全部项目"
              clearable
              style="width: 180px; margin-right: 8px"
              @change="onFilterChange"
            >
              <el-option v-for="p in projects" :key="p.id" :label="p.name" :value="p.id" />
            </el-select>
            <el-input
              v-model="searchRunId"
              placeholder="按任务ID搜索"
              clearable
              style="width: 180px; margin-right: 8px"
              @keyup.enter="loadReports"
            />
            <el-button type="primary" @click="loadReports">
              <el-icon><Search /></el-icon>
              搜索
            </el-button>
          </div>
        </div>
      </template>

      <el-table
        :data="reports"
        v-loading="loading"
        stripe
        style="width: 100%"
      >
        <el-table-column label="项目" min-width="140" show-overflow-tooltip>
          <template #default="{ row }">
            <el-tag size="small" effect="plain">{{ row.project_name || '—' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="报告 ID" width="110">
          <template #default="{ row }">
            <span class="mono-text">{{ row.id?.substring(0, 8) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="任务 ID" width="110">
          <template #default="{ row }">
            <span class="mono-text">{{ row.test_run_id?.substring(0, 8) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="通过率" width="110">
          <template #default="{ row }">
            <span v-if="row.total_tests">{{ row.passed_tests }}/{{ row.total_tests }}</span>
            <span v-else class="muted-text">—</span>
          </template>
        </el-table-column>
        <el-table-column label="质量评分" width="120">
          <template #default="{ row }">
            <el-tag :type="scoreTagType(row.quality_score)" size="default">
              {{ row.quality_score ?? '-' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="门禁结果" width="100">
          <template #default="{ row }">
            <el-tag :type="row.gate_passed ? 'success' : 'danger'" size="small">
              {{ row.gate_passed ? '通过' : '未通过' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="创建时间" width="180">
          <template #default="{ row }">
            {{ formatTime(row.created_at) }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="320" fixed="right">
          <template #default="{ row }">
            <el-button size="small" type="primary" @click="viewReport(row)">
              <el-icon><View /></el-icon>
              查看
            </el-button>
            <el-button size="small" type="success" @click="exportPdf(row)">
              <el-icon><Download /></el-icon>
              PDF
            </el-button>
            <el-button size="small" @click="shareReport(row)">
              <el-icon><Share /></el-icon>
              分享
            </el-button>
            <el-button size="small" type="warning" @click="generateReport(row)">
              重新生成
            </el-button>
            <el-button
              size="small"
              type="danger"
              text
              :disabled="!canManage"
              @click="removeReport(row)"
            >
              删除
            </el-button>
            <el-dropdown style="margin-left: 8px; vertical-align: middle" @command="(cmd: string) => gotoRelated(cmd, row)">
              <el-button size="small">
                关联数据<el-icon><ArrowDown /></el-icon>
              </el-button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="defects">缺陷列表（本任务）</el-dropdown-item>
                  <el-dropdown-item command="coverage">覆盖率（本任务）</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </template>
        </el-table-column>
      </el-table>

      <el-empty
        v-if="!loading && reports.length === 0"
        description="暂无报告，请先完成测试任务"
      />

      <!-- Pagination -->
      <div v-if="total > pageSize" class="pagination-wrapper">
        <el-pagination
          v-model:current-page="currentPage"
          :page-size="pageSize"
          :total="total"
          layout="prev, pager, next"
          @current-change="loadReports"
        />
      </div>
    </el-card>

    <!-- Report viewer dialog -->
    <el-dialog
      v-model="viewerVisible"
      :title="`测试报告 - ${selectedReport?.project_name || ''}（${selectedReport?.test_run_id?.substring(0, 8) || ''}）`"
      fullscreen
      @close="reportHtml = ''"
    >
      <div v-loading="loadingHtml" class="report-viewer">
        <iframe
          v-if="reportHtml"
          :srcdoc="reportHtml"
          class="report-iframe"
          sandbox="allow-scripts allow-same-origin"
        />
        <el-empty v-else-if="!loadingHtml" description="无法加载报告内容" />
      </div>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Search, View, Download, Share, Delete, ArrowDown } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { reportApi, projectApi } from '@/api'
import { useAuthStore } from '@/stores'

// R2：关联数据跳转（缺陷 / 覆盖率按本任务过滤）
const router = useRouter()

// ==================== State ====================

const loading = ref(false)
const loadingHtml = ref(false)
const reports = ref<any[]>([])
const total = ref(0)
const currentPage = ref(1)
const pageSize = 20
const searchRunId = ref('')
const projects = ref<any[]>([])
const filterProjectId = ref<string>('')
const authStore = useAuthStore()
const canManage = computed(() =>
  ['super_admin', 'admin', 'test_manager'].includes(authStore.role)
)

const viewerVisible = ref(false)
const selectedReport = ref<any>(null)
const reportHtml = ref('')

// ==================== Methods ====================

async function loadReports() {
  loading.value = true
  try {
    const params: any = {
      page: currentPage.value,
      page_size: pageSize,
    }
    if (searchRunId.value) {
      params.test_run_id = searchRunId.value
    }
    if (filterProjectId.value) {
      params.project_id = filterProjectId.value
    }
    const res: any = await reportApi.getList(params)
    reports.value = res?.data?.list || []
    total.value = res?.data?.total || 0
  } catch {
    reports.value = []
  } finally {
    loading.value = false
  }
}

function onFilterChange(): void {
  currentPage.value = 1
  void loadReports()
}

async function loadProjects(): Promise<void> {
  try {
    const res: any = await projectApi.getList()
        const d = res?.data ?? res
    projects.value = Array.isArray(d) ? d : d?.list || d?.items || []
  } catch {
    projects.value = []
  }
}

async function removeReport(row: any): Promise<void> {
  try {
    await ElMessageBox.confirm(
      `确定删除「${row.project_name || ''}」的报告（任务 ${row.test_run_id?.substring(0, 8)}）吗？底层测试数据不受影响。`,
      '删除确认',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }
    )
  } catch {
    return
  }
  try {
    const res: any = await reportApi.remove(row.test_run_id)
    if (res?.code === 0) {
      ElMessage.success('报告已删除')
      await loadReports()
    } else {
      ElMessage.error(res?.message || '删除失败')
    }
  } catch {
    /* 拦截器已处理 */
  }
}

async function viewReport(row: any) {
  selectedReport.value = row
  viewerVisible.value = true
  loadingHtml.value = true
  reportHtml.value = ''

  try {
    const res: any = await reportApi.getHtml(row.test_run_id)
    let html = res?.data?.html || ''
    // srcdoc iframe 无 origin，相对路径（/api/...）静默解析失败 → 图表库
    // 加载不了（图表永远"加载中"的根因）。注入 <base> 以平台后端为基准解析
    if (html && !/<base\s/i.test(html)) {
      const origin = window.location.origin
      html = html.replace(/<head([^>]*)>/i, `<head$1><base href="${origin}/">`)
    }
    reportHtml.value = html
  } catch {
    ElMessage.error('无法加载报告内容')
  } finally {
    loadingHtml.value = false
  }
}

async function exportPdf(row: any) {
  ElMessage.info('正在准备 PDF 下载...')
  try {
    const res = await fetch(`/api/reports/${row.test_run_id}/pdf`, {
      headers: apiAuthHeaders(),
    })
    if (!res.ok) {
      // 503 → 后端说 PDF 不可用，detail 里有 pdf_error 根因
      // 404 → 报告还没生成
      let detail = ''
      try {
        const body = await res.json()
        detail = body?.detail || body?.message || ''
      } catch { /* not JSON */ }
      const msg = res.status === 503
        ? `PDF 不可用：${detail}`
        : res.status === 404
          ? '报告尚未生成，请先点击「重新生成报告」'
          : `PDF 下载失败（${res.status}）：${detail}`
      ElMessage.error(msg)
      return
    }
    // 拿到 bytes → 触发下载
    const blob = await res.blob()
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `test_report_${row.test_run_id?.substring(0, 8)}.pdf`
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    URL.revokeObjectURL(url)
    ElMessage.success('PDF 下载完成')
  } catch (e: any) {
    ElMessage.error(`PDF 下载异常：${e?.message || e}`)
  }
}

function apiAuthHeaders(): Record<string, string> {
  const token = localStorage.getItem('token') || ''
  return token ? { Authorization: `Bearer ${token}` } : {}
}

async function shareReport(row: any) {
  try {
    const res: any = await reportApi.share(row.test_run_id)
    const shareUrl = res?.data?.share_url
    if (shareUrl) {
      await navigator.clipboard.writeText(shareUrl)
      ElMessage.success('分享链接已复制到剪贴板（7天有效）')
    } else {
      ElMessage.warning('无法生成分享链接')
    }
  } catch {
    ElMessage.error('生成分享链接失败')
  }
}

async function generateReport(row: any) {
  try {
    await reportApi.generate(row.test_run_id)
    ElMessage.success('报告生成已启动，请稍后刷新查看')
    setTimeout(() => loadReports(), 3000)
  } catch {
    ElMessage.error('报告生成失败')
  }
}

// R2：关联数据跳转 —— 缺陷/覆盖率按本任务过滤直达
function gotoRelated(cmd: string, row: any) {
  const rid = row?.test_run_id
  if (!rid) {
    ElMessage.warning('该报告缺少关联的测试任务 ID')
    return
  }
  if (cmd === 'defects') {
    router.push({ path: '/defects', query: { test_run_id: rid } })
  } else if (cmd === 'coverage') {
    router.push({ path: '/coverage', query: { test_run_id: rid } })
  }
}

function scoreTagType(score: number | null): string {  if (score === null || score === undefined) return 'info'
  if (score >= 80) return 'success'
  if (score >= 60) return 'warning'
  return 'danger'
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

onMounted(async () => {
  await loadReports()
  void loadProjects()
  // 支持「从仪表盘点击'查看缺陷'跳到 /report/:id」直达打开 viewer
  const route = useRoute()
  const idFromQuery = (route.query.id as string) || (route.params.id as string) || ''
  if (idFromQuery) {
    const target = reports.value.find(
      (r) => r.test_run_id === idFromQuery || r.id === idFromQuery
    )
    if (target) {
      viewReport(target)
    } else {
      // 列表里没找到（也许还没生成）—— 仍尝试拿一下报告
      ElMessage.info('正在尝试打开该测试报告...')
      viewReport({ test_run_id: idFromQuery })
    }
  }
})
</script>

<style scoped>
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.muted-text {
  color: #c0c4cc;
}

.mono-text {
  font-family: 'Courier New', Consolas, monospace;
  font-size: 13px;
  color: #606266;
}

.pagination-wrapper {
  display: flex;
  justify-content: center;
  margin-top: 16px;
}

.report-viewer {
  height: calc(100vh - 120px);
}

.report-iframe {
  width: 100%;
  height: 100%;
  border: none;
  border-radius: 4px;
}
</style>
