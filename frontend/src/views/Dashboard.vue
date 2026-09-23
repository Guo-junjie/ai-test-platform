<template>
  <div class="dashboard-page">
    <!-- 统计卡片（带跳转） -->
    <el-row :gutter="20">
      <el-col :xs="24" :sm="12" :md="6" v-for="card in statCards" :key="card.title" class="stat-column">
        <el-card shadow="hover" class="stat-card-clickable" @click="goStatCard(card)">
          <div class="stat-card">
            <el-icon :size="32" :color="card.color">
              <component :is="card.icon" />
            </el-icon>
            <div class="stat-info">
              <div class="stat-value">{{ card.value }}</div>
              <div class="stat-label">{{ card.title }}</div>
            </div>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 趋势与分布 -->
    <el-row :gutter="20" style="margin-top: var(--app-sp-5);">
      <el-col :xs="24" :lg="16">
        <el-card shadow="hover">
          <template #header>
            <div class="card-header">
              <span>质量评分趋势</span>
              <el-select v-model="days" size="small" style="width: 120px;" @change="loadData">
                <el-option label="最近 7 天" :value="7" />
                <el-option label="最近 30 天" :value="30" />
                <el-option label="最近 90 天" :value="90" />
              </el-select>
            </div>
          </template>
          <el-alert v-if="trendError" :title="trendError" type="error" show-icon :closable="false" style="margin-bottom: 12px">
            <template #default><el-button link type="primary" @click="loadTrend">重新加载</el-button></template>
          </el-alert>
          <TrendChart
            v-if="!trendError && qualityTrend.dates?.length"
            :labels="qualityTrend.dates"
            :series="[
              { name: '平均评分', data: qualityTrend.avg_scores, color: CHART_COLORS.primary },
              { name: '最高评分', data: qualityTrend.max_scores, color: CHART_COLORS.success },
              { name: '最低评分', data: qualityTrend.min_scores, color: CHART_COLORS.warning },
            ]"
            :height="280"
            y-axis-name="评分"
          />
          <el-empty v-else-if="!trendError" description="暂无质量趋势数据" />
        </el-card>
      </el-col>
      <el-col :xs="24" :lg="8" class="status-column">
        <el-card shadow="hover">
          <template #header>任务状态分布</template>
          <el-alert v-if="statisticsError" :title="statisticsError" type="error" show-icon :closable="false">
            <template #default><el-button link type="primary" @click="loadData">重新加载</el-button></template>
          </el-alert>
          <div v-else ref="statusChartRef" style="height: 280px;"></div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 最近测试任务 -->
    <el-row :gutter="20" style="margin-top: var(--app-sp-5);">
      <el-col :span="24">
        <el-card shadow="hover">
          <template #header>最近测试任务</template>
          <el-alert v-if="recentRunsError" :title="recentRunsError" type="error" show-icon :closable="false" style="margin-bottom: 12px">
            <template #default><el-button link type="primary" @click="loadRecentRuns">重新加载</el-button></template>
          </el-alert>
          <el-table :data="recentRuns" v-loading="loading" style="width: 100%">
            <el-table-column label="项目" min-width="140">
              <template #default="{ row }">
                <el-link v-if="row.project_id" type="primary" @click="goProject(row.project_id)">
                  {{ row.project_name }}
                </el-link>
                <span v-else>{{ row.project_name || '—' }}</span>
              </template>
            </el-table-column>
            <el-table-column label="状态" width="110">
              <template #default="{ row }">
                <el-tag :type="statusTagType(row.status)" size="small">{{ testStatusLabel(row.status) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="quality_score" label="质量分" width="100">
              <template #default="{ row }">
                <span>{{ row.quality_score != null ? row.quality_score : '--' }}</span>
              </template>
            </el-table-column>
            <el-table-column label="创建时间" min-width="180">
              <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
            </el-table-column>
            <el-table-column label="操作" width="160" fixed="right">
              <template #default="{ row }">
                <el-button size="small" link type="primary" @click="goRunReport(row.id)">查看报告</el-button>
                <el-button size="small" link type="warning" @click="goRunDefects(row.id)">查看缺陷</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup lang="ts">
import { CHART_COLORS } from '@/styles/chartPalette'
import { ref, onMounted, onBeforeUnmount } from 'vue'
import { useRouter } from 'vue-router'
import * as echarts from 'echarts'
import TrendChart from '@/components/TrendChart.vue'
import { dashboardApi, trendApi } from '@/api'
import { formatDateTime, normalizeStatus, testStatusLabel } from '@/utils/format'

const router = useRouter()

function goStatCard(card: { title: string }) {
  if (card.title === '发现缺陷') {
    router.push({ path: '/defects' })
  } else if (card.title === '测试任务总数') {
    router.push({ path: '/test-run' })
  } else if (card.title === '通过率' || card.title === '平均质量分') {
    router.push({ path: '/quality-trend' })
  }
}

function goProject(projectId: string) {
  router.push({ path: `/projects/${projectId}` })
}

function goRunReport(runId: string) {
  router.push({ path: `/report/${runId}` })
}

function goRunDefects(runId: string) {
  // 跳转到缺陷中心，带上 test_run_id 过滤该任务发现的缺陷
  router.push({ path: '/defects', query: { test_run_id: runId } })
}

const days = ref(30)
const loading = ref(false)
const statusChartRef = ref<HTMLElement>()
let statusChart: echarts.ECharts | null = null

const statCards = ref([
  { title: '测试任务总数', value: 0, icon: 'VideoPlay', color: CHART_COLORS.primary },
  { title: '通过率', value: '0%', icon: 'CircleCheck', color: CHART_COLORS.success },
  { title: '发现缺陷', value: 0, icon: 'Warning', color: CHART_COLORS.warning },
  { title: '平均质量分', value: '0', icon: 'Star', color: CHART_COLORS.warning },
])

const qualityTrend = ref<{ dates: string[]; avg_scores: number[]; max_scores: number[]; min_scores: number[] }>({
  dates: [],
  avg_scores: [],
  max_scores: [],
  min_scores: [],
})
const recentRuns = ref<any[]>([])
const statisticsError = ref('')
const trendError = ref('')
const recentRunsError = ref('')

function statusTagType(status: string): 'success' | 'warning' | 'info' | 'danger' | 'primary' {
  const map: Record<string, any> = {
    completed: 'success', running: 'warning', executing: 'warning',
    pending: 'info', failed: 'danger', cancelled: 'info',
  }
  return map[normalizeStatus(status)] || 'info'
}

async function loadStatistics() {
  statisticsError.value = ''
  try {
    const res: any = await dashboardApi.getStatistics(days.value)
    const d = res.data || {}
    statCards.value[0].value = d.total_runs ?? 0
    statCards.value[1].value = (d.pass_rate ?? 0) + '%'
    statCards.value[2].value = d.total_defects ?? 0
    statCards.value[3].value = (d.avg_quality_score ?? 0).toFixed(1)
    renderStatusChart(d.status_distribution || {})
  } catch (error: any) {
    statisticsError.value = error?.message || '统计数据加载失败'
  }
}

async function loadTrend() {
  trendError.value = ''
  try {
    const res: any = await trendApi.getQuality({ days: days.value })
    qualityTrend.value = res.data || qualityTrend.value
  } catch (error: any) {
    qualityTrend.value = { dates: [], avg_scores: [], max_scores: [], min_scores: [] }
    trendError.value = error?.message || '质量趋势加载失败'
  }
}

async function loadRecentRuns() {
  recentRunsError.value = ''
  try {
    const res: any = await dashboardApi.getRecentRuns(8)
    recentRuns.value = res?.data?.list || []
  } catch (error: any) {
    recentRuns.value = []
    recentRunsError.value = error?.message || '最近运行加载失败'
  }
}

function renderStatusChart(distribution: Record<string, number>) {
  if (!statusChartRef.value) return
  if (!statusChart) statusChart = echarts.init(statusChartRef.value)
  const colors: Record<string, string> = {
    pending: CHART_COLORS.textSecondary, running: CHART_COLORS.warning,
    executing: CHART_COLORS.warning, completed: CHART_COLORS.success,
    failed: CHART_COLORS.danger, cancelled: CHART_COLORS.textPlaceholder,
  }
  statusChart.setOption({
    tooltip: { trigger: 'item' },
    legend: { bottom: 0 },
    series: [
      {
        type: 'pie',
        radius: ['40%', '70%'],
        center: ['50%', '45%'],
        itemStyle: { borderRadius: 6, borderColor: CHART_COLORS.cardBg, borderWidth: 2 },
        label: { formatter: '{b}: {c}' },
        data: Object.entries(distribution).map(([rawName, value]) => ({
          name: testStatusLabel(rawName),
          value,
          itemStyle: { color: colors[normalizeStatus(rawName)] || CHART_COLORS.primary },
        })),
      },
    ],
  })
}

function resize() {
  statusChart?.resize()
}

async function loadData() {
  loading.value = true
  await Promise.all([loadStatistics(), loadTrend(), loadRecentRuns()])
  loading.value = false
}

onMounted(() => {
  loadData()
  window.addEventListener('resize', resize)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', resize)
  statusChart?.dispose()
  statusChart = null
})
</script>

<style scoped>
.stat-card {
  display: flex;
  align-items: center;
  gap: 16px;
}

.stat-info {
  display: flex;
  flex-direction: column;
}

.stat-value {
  font-size: 24px;
  font-weight: 700;
  color: var(--el-text-color-primary);
}

.stat-label {
  font-size: 13px;
  color: var(--el-text-color-secondary);
  margin-top: 4px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.stat-card-clickable {
  cursor: pointer;
  transition: transform 0.15s ease, box-shadow 0.15s ease;
}
.stat-card-clickable:hover {
  transform: translateY(-2px);
  box-shadow: 0 6px 18px rgba(var(--app-accent-rgb), 0.18);
}
.stat-column { margin-bottom: 12px; }
@media (max-width: 1199px) { .status-column { margin-top: 16px; } }
</style>
