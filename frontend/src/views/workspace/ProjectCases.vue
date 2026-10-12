<template>
  <el-card shadow="never">
    <template #header>
      <div class="head">
        <div><b>项目用例</b><p>当前项目可复用、可评审的测试资产。</p></div>
        <div class="actions">
          <el-button @click="openLibrary()">用例管理与评审</el-button>
          <el-button v-if="canCreate" type="primary" :icon="Plus" @click="openLibrary(true)">手动添加用例</el-button>
          <el-button @click="$router.push(`/case-generation?project_id=${projectId}`)">生成用例</el-button>
        </div>
      </div>
    </template>
    <el-table v-loading="loading" :data="items">
      <el-table-column prop="title" label="用例名称" min-width="240" />
      <el-table-column label="执行类型" width="120"><template #default="{ row }">{{ row.execution_kind === 'manual' ? '手工执行' : 'API 自动执行' }}</template></el-table-column>
      <el-table-column prop="priority" label="优先级" width="90" />
      <el-table-column label="评审状态" width="110"><template #default="{ row }"><el-tag effect="light">{{ reviewLabel(row.review_state) }}</el-tag></template></el-table-column>
      <el-table-column label="操作" width="160"><template #default="{ row }"><el-button v-if="row.execution_kind !== 'manual'" link type="primary" @click="$router.push(`/case-assert/${row.id}`)">配置断言</el-button><el-button link @click="$router.push(`/case-library?project_id=${projectId}&case_id=${row.id}`)">详情</el-button></template></el-table-column>
    </el-table>
    <el-empty v-if="!loading && !items.length" description="项目还没有用例，可手动添加或从文档生成">
      <el-button v-if="canCreate" type="primary" :icon="Plus" @click="openLibrary(true)">手动添加用例</el-button>
    </el-empty>
  </el-card>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Plus } from '@element-plus/icons-vue'
import { caseApi } from '@/api'
import { useAuthStore } from '@/stores'

const router = useRouter()
const auth = useAuthStore()
const projectId = String(useRoute().params.id)
const loading = ref(false)
const items = ref<any[]>([])
const canCreate = computed(() => ['super_admin', 'admin', 'test_manager', 'tester'].includes(auth.user?.role || ''))
function openLibrary(create = false) { router.push({ path: '/case-library', query: { project_id: projectId, ...(create ? { create: 'manual' } : {}) } }) }
function reviewLabel(value: string) { return ({ draft: '草稿', pending: '待评审', approved: '已通过', changes_requested: '需修改' } as Record<string, string>)[value] || value }
onMounted(async () => { loading.value = true; try { const response: any = await caseApi.list({ project_id: projectId, page: 1, page_size: 50 }); items.value = response?.data?.items || [] } finally { loading.value = false } })
</script>

<style scoped>
.head { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; }.head p { margin: 5px 0 0; color: var(--app-text-secondary); font-size: 13px; }.actions { display: flex; flex-wrap: wrap; gap: 8px; }.actions .el-button { margin-left: 0; }
@media (max-width: 768px) { .head { flex-direction: column; } }
</style>
