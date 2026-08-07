<template>
  <el-card shadow="hover" class="score-card">
    <template #header>
      <div class="card-header">
        <span>质量评分</span>
        <el-tag :type="gateTagType" size="small">
          {{ gatePassed ? '门禁通过' : '门禁未过' }}
        </el-tag>
      </div>
    </template>
    <div ref="gaugeRef" style="height: 220px;"></div>
    <div class="score-meta">
      <span v-if="gateDetails?.violations?.length" class="violations">
        未通过项：{{ gateDetails.violations.length }}
      </span>
      <span v-else class="ok-text">所有门禁规则均已满足</span>
    </div>
  </el-card>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch, onBeforeUnmount } from 'vue'
import * as echarts from 'echarts'

/**
 * 质量评分仪表盘卡片
 * 颜色分级：>=80 绿 / >=60 黄 / <60 红
 */
const props = defineProps<{
  score: number
  gatePassed?: boolean
  gateDetails?: any
}>()

const gaugeRef = ref<HTMLElement>()
let chart: echarts.ECharts | null = null

const gateTagType = computed(() => (props.gatePassed ? 'success' : 'danger'))

function scoreColor(): string {
  if (props.score >= 80) return '#67c23a'
  if (props.score >= 60) return '#e6a23c'
  return '#f56c6c'
}

function render() {
  if (!gaugeRef.value) return
  if (!chart) chart = echarts.init(gaugeRef.value)

  const value = props.score || 0
  chart.setOption({
    series: [
      {
        type: 'gauge',
        startAngle: 200,
        endAngle: -20,
        min: 0,
        max: 100,
        radius: '90%',
        center: ['50%', '60%'],
        axisLine: {
          lineStyle: {
            width: 18,
            color: [
              [0.6, '#f56c6c'],
              [0.8, '#e6a23c'],
              [1, '#67c23a'],
            ],
          },
        },
        pointer: { itemStyle: { color: scoreColor() } },
        axisTick: { distance: -18, length: 4, lineStyle: { color: '#fff' } },
        splitLine: { distance: -18, length: 10, lineStyle: { color: '#fff', width: 2 } },
        axisLabel: { distance: 8, color: '#909399', fontSize: 10 },
        detail: {
          valueAnimation: true,
          formatter: '{value}',
          color: scoreColor(),
          fontSize: 28,
          offsetCenter: [0, '40%'],
        },
        data: [{ value: Number(value.toFixed(1)) }],
      },
    ],
  })
}

function resize() {
  chart?.resize()
}

onMounted(() => {
  render()
  window.addEventListener('resize', resize)
})

watch(
  () => props.score,
  () => render()
)

onBeforeUnmount(() => {
  window.removeEventListener('resize', resize)
  chart?.dispose()
  chart = null
})
</script>

<style scoped>
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.score-meta {
  text-align: center;
  margin-top: 8px;
  font-size: 13px;
}

.violations {
  color: #f56c6c;
}

.ok-text {
  color: #67c23a;
}
</style>
