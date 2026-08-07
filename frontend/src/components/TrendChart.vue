<template>
  <div ref="chartRef" :style="{ height: height + 'px', width: '100%' }"></div>
</template>

<script setup lang="ts">
import { ref, onMounted, watch, onBeforeUnmount } from 'vue'
import * as echarts from 'echarts'

/**
 * 通用趋势折线图组件
 * 支持：质量分 / 通过率 / 缺陷数 等时序数据展示
 */
const props = defineProps<{
  labels: string[]
  series: Array<{
    name: string
    data: number[]
    type?: 'line' | 'bar'
    color?: string
  }>
  height?: number
  yAxisName?: string
}>()

const chartRef = ref<HTMLElement>()
let chart: echarts.ECharts | null = null

function render() {
  if (!chartRef.value) return
  if (!chart) chart = echarts.init(chartRef.value)

  chart.setOption({
    tooltip: { trigger: 'axis' },
    legend: {
      data: props.series.map((s) => s.name),
      top: 0,
    },
    grid: { left: 50, right: 30, top: 40, bottom: 30 },
    xAxis: {
      type: 'category',
      data: props.labels,
      axisLabel: { color: '#909399' },
    },
    yAxis: {
      type: 'value',
      name: props.yAxisName || '',
      axisLabel: { color: '#909399' },
      splitLine: { lineStyle: { type: 'dashed', color: '#e5e5e5' } },
    },
    series: props.series.map((s) => ({
      name: s.name,
      type: s.type || 'line',
      data: s.data,
      smooth: s.type !== 'bar',
      symbolSize: 6,
      itemStyle: s.color ? { color: s.color } : undefined,
      lineStyle: s.color ? { color: s.color } : undefined,
      barMaxWidth: 24,
    })),
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
  () => props,
  () => render(),
  { deep: true }
)

onBeforeUnmount(() => {
  window.removeEventListener('resize', resize)
  chart?.dispose()
  chart = null
})
</script>
