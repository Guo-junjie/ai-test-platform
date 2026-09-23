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
            <div class="ws-name">{{ project?.name || '...' }}</div>
            <div class="ws-sub">
              <el-tag size="small" :type="projectKindTag(project?.project_kind)">{{ projectKindLabel(project?.project_kind) }}</el-tag>
              <el-tag size="small" effect="plain">{{ sourceLabel(project?.source_type) }}</el-tag>
              <span v-if="project?.description" class="ws-desc">{{ project.description }}</span>
            </div>
          </div>
        </div>
        <div class="ws-actions">
          <ProjectMembers :project-id="projectId" :owner-id="project?.owner_id" />
          <el-button v-if="hasCapability('test_execution')" type="primary" @click="$router.push(`/projects/${projectId}/plans`)">执行测试计划</el-button>
        </div>
      </div>
      <!-- 分区导航 -->
      <el-tabs v-model="activeTab" class="ws-tabs" @tab-change="onTab">
        <el-tab-pane label="概览" name="overview" />
        <el-tab-pane label="测试上下文" name="context" />
        <el-tab-pane v-if="hasCapability('test_plans')" label="测试计划" name="plans" />
        <el-tab-pane v-if="hasCapability('test_execution')" label="运行中心" name="runs" />
        <el-tab-pane v-if="hasCapability('reports')" label="质量结果" name="quality" />
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
import { projectApi } from '@/api'
import ProjectMembers from '@/components/ProjectMembers.vue'

const SOURCE_LABELS: Record<string, string> = { github: 'GitHub', svn: 'SVN', upload: '本地上传' }
const PROJECT_KIND_LABELS: Record<string, string> = {
  full: '完整测试项目', api_testing: '接口测试项目', source_analysis: '源码分析项目',
}

export default defineComponent({
  name: 'ProjectWorkspace',
  components: { ArrowLeft, ProjectMembers },
  data() {
    return {
      projectId: (this.$route.params.id as string) || '',
      project: null as any,
    }
  },
  computed: {
    activeTab(): string {
      const name = this.$route.name as string
      return name === 'ws-plans' ? 'plans'
        : name === 'ws-runs' ? 'runs'
        : name === 'ws-context' ? 'context'
        : name === 'ws-quality' ? 'quality'
        : 'overview'
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
      this.$router.push(`/projects/${this.projectId}/${tab}`)
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
    this.loadProject()
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
.ws-name {
  font-size: 18px;
  font-weight: 700;
  color: var(--el-text-color-primary);
}
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
</style>
