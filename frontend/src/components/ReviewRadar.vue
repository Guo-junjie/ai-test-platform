<template>
  <div ref="chartRef" :style="{ height: height + 'px', width: '100%' }"></div>
</template>

<script setup lang="ts">
import { ref, onMounted, watch, onBeforeUnmount } from 'vue'
import * as echarts from 'echarts'

const props = defineProps<{
  scores?: Record<string, number>
  height?: number
}>()

const DIM_LABELS: Record<string, string> = {
  basic_info: '基本信息',
  request_params: '请求参数',
  response_definition: '响应定义',
  security_auth: '安全认证',
}

const chartRef = ref<HTMLElement>()
let chart: echarts.ECharts | null = null

function indicator() {
  return Object.keys(DIM_LABELS).map((k) => ({
    name: DIM_LABELS[k] || k,
    max: 5,
  }))
}

function value() {
  return Object.keys(DIM_LABELS).map((k) => props.scores?.[k] ?? 0)
}

function render() {
  if (!chartRef.value) return
  if (!chart) chart = echarts.init(chartRef.value)
  chart.setOption({
    tooltip: {},
    radar: {
      indicator: indicator(),
      radius: '65%',
      axisName: { color: '#606266' },
      splitArea: { areaStyle: { color: ['#fafafa', '#fff'] } },
    },
    series: [
      {
        type: 'radar',
        data: [
          {
            value: value(),
            name: '评分',
            areaStyle: { color: 'rgba(64,158,255,0.25)' },
            lineStyle: { color: '#409eff' },
            itemStyle: { color: '#409eff' },
          },
        ],
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
  () => props.scores,
  () => render(),
  { deep: true },
)

onBeforeUnmount(() => {
  window.removeEventListener('resize', resize)
  chart?.dispose()
  chart = null
})
</script>
