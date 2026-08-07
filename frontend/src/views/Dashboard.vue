<template>
  <div class="dashboard-page">
    <!-- 统计卡片 -->
    <el-row :gutter="20">
      <el-col :span="6" v-for="card in statCards" :key="card.title">
        <el-card shadow="hover">
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
    <el-row :gutter="20" style="margin-top: 20px;">
      <el-col :span="16">
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
          <TrendChart
            v-if="qualityTrend.dates?.length"
            :labels="qualityTrend.dates"
            :series="[
              { name: '平均评分', data: qualityTrend.avg_scores, color: '#409eff' },
              { name: '最高评分', data: qualityTrend.max_scores, color: '#67c23a' },
              { name: '最低评分', data: qualityTrend.min_scores, color: '#e6a23c' },
            ]"
            :height="280"
            y-axis-name="评分"
          />
          <el-empty v-else description="暂无质量趋势数据" />
        </el-card>
      </el-col>
      <el-col :span="8">
        <el-card shadow="hover">
          <template #header>任务状态分布</template>
          <div ref="statusChartRef" style="height: 280px;"></div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 最近测试任务 -->
    <el-row :gutter="20" style="margin-top: 20px;">
      <el-col :span="24">
        <el-card shadow="hover">
          <template #header>最近测试任务</template>
          <el-table :data="recentRuns" v-loading="loading" style="width: 100%">
            <el-table-column prop="project_name" label="项目" min-width="140" />
            <el-table-column prop="status" label="状态" width="110">
              <template #default="{ row }">
                <el-tag :type="statusTagType(row.status)" size="small">{{ row.status }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="pass_rate" label="通过率" width="100">
              <template #default="{ row }">
                <span>{{ row.pass_rate != null ? row.pass_rate + '%' : '--' }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="quality_score" label="质量分" width="100">
              <template #default="{ row }">
                <span>{{ row.quality_score != null ? row.quality_score : '--' }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="created_at" label="创建时间" min-width="170" />
          </el-table>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount } from 'vue'
import * as echarts from 'echarts'
import TrendChart from '@/components/TrendChart.vue'
import { dashboardApi, trendApi, testRunApi } from '@/api'

const days = ref(30)
const loading = ref(false)
const statusChartRef = ref<HTMLElement>()
let statusChart: echarts.ECharts | null = null

const statCards = ref([
  { title: '测试任务总数', value: 0, icon: 'VideoPlay', color: '#409eff' },
  { title: '通过率', value: '0%', icon: 'CircleCheck', color: '#67c23a' },
  { title: '发现缺陷', value: 0, icon: 'Warning', color: '#e6a23c' },
  { title: '平均质量分', value: '0', icon: 'Star', color: '#e6a23c' },
])

const qualityTrend = ref<{ dates: string[]; avg_scores: number[]; max_scores: number[]; min_scores: number[] }>({
  dates: [],
  avg_scores: [],
  max_scores: [],
  min_scores: [],
})
const recentRuns = ref<any[]>([])

function statusTagType(status: string): 'success' | 'warning' | 'info' | 'danger' | 'primary' {
  const map: Record<string, any> = {
    COMPLETED: 'success',
    RUNNING: 'warning',
    PENDING: 'info',
    FAILED: 'danger',
  }
  return map[status] || 'info'
}

async function loadStatistics() {
  try {
    const res: any = await dashboardApi.getStatistics(days.value)
    const d = res.data || {}
    statCards.value[0].value = d.total_runs ?? 0
    statCards.value[1].value = (d.pass_rate ?? 0) + '%'
    statCards.value[2].value = d.total_defects ?? 0
    statCards.value[3].value = (d.avg_quality_score ?? 0).toFixed(1)
    renderStatusChart(d.status_distribution || {})
  } catch {
    /* 静默失败，保留默认值 */
  }
}

async function loadTrend() {
  try {
    const res: any = await trendApi.getQuality({ days: days.value })
    qualityTrend.value = res.data || qualityTrend.value
  } catch {
    /* 忽略 */
  }
}

async function loadRecentRuns() {
  try {
    const res: any = await testRunApi.list()
    const list = Array.isArray(res?.data) ? res.data : res?.data?.list || []
    recentRuns.value = list.slice(0, 8)
  } catch {
    recentRuns.value = []
  }
}

function renderStatusChart(distribution: Record<string, number>) {
  if (!statusChartRef.value) return
  if (!statusChart) statusChart = echarts.init(statusChartRef.value)
  const colors: Record<string, string> = {
    PENDING: '#909399',
    RUNNING: '#e6a23c',
    COMPLETED: '#67c23a',
    FAILED: '#f56c6c',
    CANCELLED: '#c0c4cc',
  }
  statusChart.setOption({
    tooltip: { trigger: 'item' },
    legend: { bottom: 0 },
    series: [
      {
        type: 'pie',
        radius: ['40%', '70%'],
        center: ['50%', '45%'],
        itemStyle: { borderRadius: 6, borderColor: '#fff', borderWidth: 2 },
        label: { formatter: '{b}: {c}' },
        data: Object.entries(distribution).map(([name, value]) => ({
          name,
          value,
          itemStyle: { color: colors[name] || '#409eff' },
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
  color: #303133;
}

.stat-label {
  font-size: 13px;
  color: #909399;
  margin-top: 4px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
</style>
