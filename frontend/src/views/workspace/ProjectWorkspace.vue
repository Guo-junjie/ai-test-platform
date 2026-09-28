<template>
  <div class="project-workspace">
    <!-- 项目头 -->
    <el-card shadow="hover" class="ws-header">
      <div class="ws-header-inner">
        <div class="ws-title">
          <el-button text @click="$router.push('/projects')">
            <el-icon><ArrowLeft /></el-icon>
          </el-button>
          <div>
            <div class="context-line">
              <el-select v-model="projectId" filterable class="project-switcher" aria-label="切换项目" @change="onProjectSwitch"><el-option v-for="item in projects" :key="item.id" :label="item.name" :value="item.id" /></el-select>
              <span class="context-separator">/</span>
              <el-select v-model="environmentId" clearable class="environment-switcher" placeholder="选择执行环境" aria-label="切换执行环境" @change="onEnvironmentSwitch"><el-option v-for="item in environments" :key="item.id" :label="item.name" :value="item.id"><span>{{item.name}}</span><el-tag class="env-status" size="small" :type="item.status==='published'?'success':'info'">{{item.status==='published'?'已发布':'草稿'}}</el-tag></el-option></el-select>
            </div>
            <div class="ws-sub">
              <el-tag size="small" :type="projectKindTag(project?.project_kind)">{{ projectKindLabel(project?.project_kind) }}</el-tag>
              <el-tag size="small" effect="plain">{{ sourceLabel(project?.source_type) }}</el-tag>
              <span v-if="project?.description" class="ws-desc">{{ project.description }}</span>
            </div>
          </div>
        </div>
        <div class="ws-actions">
          <el-tag v-if="selectedEnvironment" :type="selectedEnvironment.status === 'published' ? 'success' : 'warning'" effect="plain">{{ selectedEnvironment.status === 'published' ? '环境可执行' : '环境未发布' }}</el-tag>
          <el-button v-if="hasCapability('test_execution')" type="primary" @click="$router.push(`/projects/${projectId}/plans`)">执行测试计划</el-button>
        </div>
      </div>
      <!-- 分区导航 -->
      <el-tabs v-model="activeTab" class="ws-tabs" @tab-change="onTab">
        <el-tab-pane label="概览" name="overview" />
        <el-tab-pane label="用例" name="cases" />
        <el-tab-pane v-if="hasCapability('test_plans')" label="测试计划" name="plans" />
        <el-tab-pane v-if="hasCapability('test_execution')" label="执行记录" name="runs" />
        <el-tab-pane v-if="hasCapability('reports')" label="质量结果" name="quality" />
        <el-tab-pane label="环境" name="environments" />
        <el-tab-pane label="成员" name="members" />
        <el-tab-pane label="设置" name="settings" />
      </el-tabs>
    </el-card>

    <div class="ws-body">
      <router-view />
    </div>
  </div>
</template>

<script lang="ts">
/**
 * ProjectWorkspace —— 项目工作区（企业化改造 M4，方案 3.3）
 *
 * 项目上下文内的统一壳：概览 / 测试上下文 / 测试计划 / 运行中心 / 质量结果。
 * 现有功能页按分区逐步收编（先改壳不重写）；分区路由见 router/index.ts。
 */
import { defineComponent } from 'vue'
import { ArrowLeft } from '@element-plus/icons-vue'
import { environmentApi, projectApi } from '@/api'

const SOURCE_LABELS: Record<string, string> = { github: 'GitHub', svn: 'SVN', upload: '本地上传' }
const PROJECT_KIND_LABELS: Record<string, string> = {
  full: '完整测试项目', api_testing: '接口测试项目', source_analysis: '源码分析项目',
}

export default defineComponent({
  name: 'ProjectWorkspace',
  components: { ArrowLeft },
  data() {
    return {
      projectId: (this.$route.params.id as string) || '',
      project: null as any,
      projects: [] as any[],
      environments: [] as any[],
      environmentId: String(this.$route.query.env_id || ''),
    }
  },
  computed: {
    activeTab(): string {
      const name = this.$route.name as string
      return name === 'ws-plans' ? 'plans'
        : name === 'ws-runs' ? 'runs'
        : name === 'ws-cases' ? 'cases'
        : name === 'ws-quality' ? 'quality'
        : name === 'ws-environments' ? 'environments'
        : name === 'ws-members' ? 'members'
        : name === 'ws-settings' ? 'settings'
        : 'overview'
    },
    selectedEnvironment(): any {
      return this.environments.find((item: any) => item.id === this.environmentId) || null
    },
  },
  methods: {
    sourceLabel(t?: string): string {
      return SOURCE_LABELS[t || ''] || t || '—'
    },
    projectKindLabel(kind?: string): string {
      return PROJECT_KIND_LABELS[kind || 'full'] || kind || '完整测试项目'
    },
    projectKindTag(kind?: string): 'success' | 'warning' | 'info' {
      return kind === 'api_testing' ? 'success' : kind === 'source_analysis' ? 'warning' : 'info'
    },
    hasCapability(capability: string): boolean {
      return (this.project?.capabilities || []).includes(capability)
    },
    onTab(tab: string): void {
      this.$router.push({ path: `/projects/${this.projectId}/${tab}`, query: this.environmentId ? { env_id: this.environmentId } : {} })
    },
    onProjectSwitch(id: string): void {
      this.environmentId = ''
      this.$router.push(`/projects/${id}/${this.activeTab}`)
    },
    onEnvironmentSwitch(id: string): void {
      this.$router.replace({ path: this.$route.path, query: id ? { ...this.$route.query, env_id: id } : {} })
    },
    async loadProjects(): Promise<void> {
      const res: any = await projectApi.getList()
      const data = res?.data ?? res
      this.projects = Array.isArray(data) ? data : data?.items || data?.list || []
    },
    async loadEnvironments(): Promise<void> {
      try {
        const res: any = await environmentApi.list(this.projectId)
        this.environments = res?.data?.items || res?.data?.list || (Array.isArray(res?.data) ? res.data : [])
        if (!this.environmentId) this.environmentId = this.environments.find((item: any) => item.status === 'published')?.id || ''
      } catch { this.environments = [] }
    },
    async loadProject(): Promise<void> {
      try {
        const res: any = await projectApi.get(this.projectId)
        this.project = res?.data || null
      } catch {
        this.project = null
      }
    },
  },
  mounted() {
    Promise.all([this.loadProjects(), this.loadProject(), this.loadEnvironments()])
  },
  watch: {
    '$route.params.id'(value: string) {
      if (!value || value === this.projectId) return
      this.projectId = value
      this.project = null
      this.environments = []
      Promise.all([this.loadProject(), this.loadEnvironments()])
    },
  },
})
</script>

<style scoped>
.ws-header-inner {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 4px;
}
.ws-title {
  display: flex;
  align-items: center;
  gap: 8px;
}
.context-line { display: flex; align-items: center; gap: 8px; }
.project-switcher { width: 250px; }.environment-switcher { width: 220px; }.context-separator { color: var(--el-text-color-placeholder); }.env-status { float: right; margin-top: 6px; }
.ws-sub {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 4px;
}
.ws-desc {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.ws-tabs :deep(.el-tabs__header) {
  margin-bottom: 0;
}
.ws-body {
  margin-top: 16px;
}
@media (max-width: 760px) { .ws-header-inner { flex-direction: column; gap: 12px; }.context-line { flex-wrap: wrap; }.project-switcher,.environment-switcher { width: min(300px, 72vw); }.ws-actions { width: 100%; display: flex; justify-content: flex-end; } }
</style>
