<template>
  <div class="case-generation">
    <PageHeader title="智能用例生成" description="从需求文档或接口文档生成可追溯的用例草稿，生成结果统一进入用例管理与评审。">
      <template #actions>
        <el-button :icon="EditPen" :disabled="!projectId" @click="openManualCreate">手动录入</el-button>
        <el-button :icon="UploadFilled" :disabled="!projectId" @click="openImport">批量导入</el-button>
        <el-button type="primary" plain @click="goCaseLibrary">进入用例管理与评审</el-button>
      </template>
    </PageHeader>

    <el-card shadow="never" class="source-card">
      <div class="source-toolbar">
        <el-tabs v-model="activeSource" class="source-tabs">
          <el-tab-pane name="requirement">
            <template #label><span class="tab-label"><el-icon><Document /></el-icon>需求文档生成</span></template>
          </el-tab-pane>
          <el-tab-pane name="interface">
            <template #label><span class="tab-label"><el-icon><Connection /></el-icon>接口文档生成</span></template>
          </el-tab-pane>
        </el-tabs>
        <el-select v-model="projectId" filterable placeholder="选择项目" class="project-select" @change="syncProjectQuery">
          <el-option v-for="project in projects" :key="project.id" :label="project.name" :value="project.id" />
        </el-select>
      </div>
      <p class="source-description">{{ sourceDescription }}</p>
      <el-alert
        type="info"
        :closable="false"
        show-icon
        title="人工录入和文件导入已统一到用例管理与评审，避免字段、校验和来源记录不一致。"
      />
    </el-card>

    <keep-alive>
      <component :is="activeComponent" :key="`${activeSource}-${projectId}`" />
    </keep-alive>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Connection, Document, EditPen, UploadFilled } from '@element-plus/icons-vue'
import RequirementParse from '@/views/RequirementParse.vue'
import DocParser from '@/views/DocParser.vue'
import PageHeader from '@/components/PageHeader.vue'
import { projectApi } from '@/api'

type Source = 'requirement' | 'interface'

const route = useRoute()
const router = useRouter()
const projects = ref<any[]>([])
const projectId = ref(String(route.query.project_id || ''))

const activeSource = computed<Source>({
  get: () => String(route.query.source) === 'interface' ? 'interface' : 'requirement',
  set: (source) => router.replace({ path: '/case-generation', query: { ...route.query, source } }),
})
const activeComponent = computed(() => activeSource.value === 'interface' ? DocParser : RequirementParse)
const sourceDescription = computed(() => activeSource.value === 'requirement'
  ? '上传 PRD 或验收标准，解析需求并生成可追溯的功能用例草稿。'
  : '导入 OpenAPI、Swagger 或 HAR，建立接口资产并生成可执行的 API 用例。')

function libraryQuery(extra: Record<string, string> = {}) {
  return { ...(projectId.value ? { project_id: projectId.value } : {}), ...extra }
}
function goCaseLibrary() { router.push({ path: '/case-library', query: libraryQuery() }) }
function openManualCreate() { router.push({ path: '/case-library', query: libraryQuery({ create: 'manual' }) }) }
function openImport() { router.push({ path: '/case-library', query: libraryQuery({ action: 'import' }) }) }
function syncProjectQuery() {
  router.replace({ path: '/case-generation', query: { ...route.query, project_id: projectId.value || undefined } })
}
async function loadProjects() {
  const response: any = await projectApi.getList()
  projects.value = Array.isArray(response?.data) ? response.data : (response?.data?.items || response?.data?.list || [])
  if (!projects.value.some(project => project.id === projectId.value)) projectId.value = projects.value[0]?.id || ''
}

onMounted(loadProjects)
</script>

<style scoped>
.case-generation { display: grid; gap: 16px; }
.source-card { padding-bottom: 2px; }
.source-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.source-tabs { flex: 1; min-width: 0; }
.source-tabs :deep(.el-tabs__content) { display: none; }
.tab-label { display: inline-flex; align-items: center; gap: 7px; padding: 0 8px; font-weight: 600; }
.source-description { margin: 4px 0 14px; color: var(--app-text-secondary); font-size: 13px; }
.project-select { width: 260px; }
@media (max-width: 720px) {
  .source-toolbar { align-items: stretch; flex-direction: column-reverse; }
  .project-select { width: 100%; }
}
</style>
