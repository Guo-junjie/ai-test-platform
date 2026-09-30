<template>
  <div class="page-header">
    <div class="page-copy">
      <h1>{{ title }}</h1>
      <p v-if="resolvedDescription">{{ resolvedDescription }}</p>
    </div>
    <div v-if="$slots.actions || $slots.default" class="actions">
      <slot name="actions"><slot /></slot>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ title: string; subtitle?: string; description?: string }>()
const resolvedDescription = computed(() => props.description || props.subtitle || '')
</script>

<style scoped>
.page-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; margin-bottom: 20px; }
.page-copy { min-width: 0; }
.page-header h1 { margin: 0; color: var(--app-text-primary); font-size: 19px; font-weight: 600; line-height: 1.35; letter-spacing: -.2px; }
.page-header p { max-width: 820px; margin: 5px 0 0; color: var(--app-text-secondary); font-size: 13px; line-height: 1.5; }
.actions { display: flex; flex: none; align-items: center; gap: 8px; flex-wrap: wrap; }
@media (max-width: 768px) {
  .page-header { flex-direction: column; }
  .actions { width: 100%; }
}
</style>
