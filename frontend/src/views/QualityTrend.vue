<template>
  <div class="quality-trend-page">
    <el-card shadow="hover">
      <template #header>
        <div class="card-header">
          <span>质量趋势看板</span>
          <div class="header-actions">
            <el-select v-model="days" style="width: 150px;" @change="loadAll">
              <el-option label="最近 7 天" :value="7" />
              <el-option label="最近 30 天" :value="30" />
              <el-option label="最近 90 天" :value="90" />
            </el-select>
            <el-button type="primary" size="small" @click="loadAll">刷新</el-button>
          </div>
        </div>
      </template>

      <!-- 汇总卡片 -->
      <el-row :gutter="16">
        <el-col :span="6" v-for="card in summaryCards" :key="card.title">
          <el-card shadow="never" class="summary-card">
            <div class="summary-value">{{ card.value }}</div>
            <div class="summary-label">{{ card.title }}</div>
          </el-card>
        </el-col>
      </el-row>

      <el-row :gutter="20" style="margin-top: 20px;">
        <el-col :span="12">
          <el-card shadow="never">
            <template #header>质量评分趋势</template>
            <TrendChart
              v-if="qualityTrend.dates?.length"
              :labels="qualityTrend.dates"
              :series="[
                { name: '平均评分', data: qualityTrend.avg_scores, color: '#409eff' },
                { name: '最高评分', data: qualityTrend.max_scores, color: '#67c23a' },
                { name: '最低评分', data: qualityTrend.min_scores, color: '#f56c6c' },
              ]"
              :height="300"
              y-axis-name="评分"
            />
            <el-empty v-else description="暂无数据" />
          </el-card>
        </el-col>
        <el-col :span="12">
          <el-card shadow="never">
            <template #header>接口通过率趋势</template>
            <TrendChart
              v-if="passRateTrend.dates?.length"
              :labels="passRateTrend.dates"
              :series="[
                { name: '通过率', data: passRateTrend.pass_rates, type: 'line', color: '#67c23a' },
                { name: '门禁通过数', data: passRateTrend.gate_passed, type: 'bar', color: '#409eff' },
              ]"
              :height="300"
              y-axis-name="%"
            />
            <el-empty v-else description="暂无数据" />
          </el-card>
        </el-col>
      </el-row>

      <el-row :gutter="20" style="margin-top: 20px;">
        <el-col :span="12">
          <el-card shadow="never">
            <template #header>缺陷数量趋势</template>
            <TrendChart
              v-if="defectTrend.dates?.length"
              :labels="defectTrend.dates"
              :series="[
                { name: '缺陷总数', data: defectTrend.totals, type: 'bar', color: '#f56c6c' },
                { name: 'P0', data: defectTrend.p0, color: '#f56c6c' },
                { name: 'P1', data: defectTrend.p1, color: '#e6a23c' },
                { name: 'P2', data: defectTrend.p2, color: '#409eff' },
              ]"
              :height="300"
              y-axis-name="数量"
            />
            <el-empty v-else description="暂无数据" />
          </el-card>
        </el-col>
        <el-col :span="12">
          <el-card shadow="never">
            <template #header>运行趋势</template>
            <TrendChart
              v-if="passRateTrend.dates?.length"
              :labels="passRateTrend.dates"
              :series="[
                { name: '总任务', data: passRateTrend.totals, type: 'bar', color: '#909399' },
                { name: '完成任务', data: passRateTrend.completed, type: 'bar', color: '#409eff' },
              ]"
              :height="300"
              y-axis-name="数量"
            />
            <el-empty v-else description="暂无数据" />
          </el-card>
        </el-col>
      </el-row>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import TrendChart from '@/components/TrendChart.vue'
import { trendApi } from '@/api'

const days = ref(30)

const summaryCards = ref([
  { title: '总运行数', value: 0 },
  { title: '门禁通过数', value: 0 },
  { title: '平均通过率', value: '0%' },
  { title: '平均质量分', value: 0 },
])

const qualityTrend = ref<any>({ dates: [], avg_scores: [], max_scores: [], min_scores: [] })
const passRateTrend = ref<any>({ dates: [], totals: [], completed: [], gate_passed: [], pass_rates: [] })
const defectTrend = ref<any>({ dates: [], totals: [], p0: [], p1: [], p2: [], p3: [] })

async function loadSummary() {
  try {
    const res: any = await trendApi.getSummary({ days: days.value })
    const d = res.data || {}
    summaryCards.value[0].value = d.total_runs ?? 0
    summaryCards.value[1].value = d.gate_passed_count ?? 0
    summaryCards.value[2].value = (d.pass_rate ?? 0) + '%'
    summaryCards.value[3].value = d.avg_quality_score ?? 0
  } catch {
    /* 忽略 */
  }
}

async function loadQuality() {
  try {
    const res: any = await trendApi.getQuality({ days: days.value })
    if (res.data) qualityTrend.value = res.data
  } catch {
    /* 忽略 */
  }
}

async function loadPassRate() {
  try {
    const res: any = await trendApi.getPassRate({ days: days.value })
    if (res.data) passRateTrend.value = res.data
  } catch {
    /* 忽略 */
  }
}

async function loadDefect() {
  try {
    const res: any = await trendApi.getDefect({ days: days.value })
    if (res.data) defectTrend.value = res.data
  } catch {
    /* 忽略 */
  }
}

function loadAll() {
  loadSummary()
  loadQuality()
  loadPassRate()
  loadDefect()
}

onMounted(loadAll)
</script>

<style scoped>
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.header-actions {
  display: flex;
  gap: 12px;
  align-items: center;
}

.summary-card {
  text-align: center;
  padding: 8px 0;
}

.summary-value {
  font-size: 28px;
  font-weight: 700;
  color: #303133;
}

.summary-label {
  font-size: 13px;
  color: #909399;
  margin-top: 4px;
}
</style>
