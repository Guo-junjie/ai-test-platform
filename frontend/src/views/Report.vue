<template>
  <div class="report-page">
    <!-- Report list -->
    <el-card shadow="hover">
      <template #header>
        <div class="card-header">
          <span>测试报告</span>
          <div>
            <el-input
              v-model="searchRunId"
              placeholder="按任务ID搜索"
              clearable
              style="width: 200px; margin-right: 8px"
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
        <el-table-column label="报告 ID" width="120">
          <template #default="{ row }">
            <span class="mono-text">{{ row.id?.substring(0, 8) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="任务 ID" width="120">
          <template #default="{ row }">
            <span class="mono-text">{{ row.test_run_id?.substring(0, 8) }}</span>
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
      :title="`测试报告 - ${selectedReport?.test_run_id?.substring(0, 8) || ''}`"
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
import { ref, onMounted } from 'vue'
import { Search, View, Download, Share } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { reportApi } from '@/api'

// ==================== State ====================

const loading = ref(false)
const loadingHtml = ref(false)
const reports = ref<any[]>([])
const total = ref(0)
const currentPage = ref(1)
const pageSize = 20
const searchRunId = ref('')

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
    const res: any = await reportApi.getList(params)
    reports.value = res?.data?.list || []
    total.value = res?.data?.total || 0
  } catch {
    reports.value = []
  } finally {
    loading.value = false
  }
}

async function viewReport(row: any) {
  selectedReport.value = row
  viewerVisible.value = true
  loadingHtml.value = true
  reportHtml.value = ''

  try {
    const res: any = await reportApi.getHtml(row.test_run_id)
    reportHtml.value = res?.data?.html || ''
  } catch {
    ElMessage.error('无法加载报告内容')
  } finally {
    loadingHtml.value = false
  }
}

async function exportPdf(row: any) {
  try {
    ElMessage.info('正在生成 PDF 下载...')
    const url = `/api/reports/${row.test_run_id}/pdf`
    const link = document.createElement('a')
    link.href = url
    link.download = `test_report_${row.test_run_id?.substring(0, 8)}.pdf`
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
  } catch {
    ElMessage.error('PDF 下载失败')
  }
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

function scoreTagType(score: number | null): string {
  if (score === null || score === undefined) return 'info'
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

onMounted(() => {
  loadReports()
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
