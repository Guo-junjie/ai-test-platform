<template><el-tag size="small" :type="resolved.type" effect="light"><span class="dot"></span>{{ resolved.label }}</el-tag></template>
<script setup lang="ts">
import { computed } from 'vue'
import { RUN_STATUS, REVIEW_STATUS } from '@/constants/status'

type StatusEntry = { label: string; type?: string }
const props = withDefaults(defineProps<{
  value?: string
  status?: string
  kind?: 'run' | 'review'
  label?: string
  map?: Record<string, StatusEntry>
}>(), { value: '', status: '', kind: 'run' })

const resolved = computed(() => {
  const raw = props.status || props.value
  if (props.label) return { label: props.label, type: '' }
  const dictionary = props.map || (props.kind === 'review' ? REVIEW_STATUS : RUN_STATUS)
  return dictionary[raw] || { label: raw || '未知', type: 'info' }
})
</script>
<style scoped>.dot{display:inline-block;width:5px;height:5px;border-radius:50%;background:currentColor;margin-right:5px;vertical-align:1px}</style>
