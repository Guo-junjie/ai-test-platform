<template>
  <div class="ws-context">
    <el-card shadow="hover">
      <template #header>代码与文档 —— 平台测试本项目所需的事实</template>
      <el-row :gutter="16">
        <el-col :xs="24" :md="12">
          <div class="ctx-card" @click="$router.push('/doc-parser')">
            <div class="ctx-title">接口文档解析</div>
            <div class="ctx-desc">上传 OpenAPI/HAR 文档 → 解析出接口 → 导入接口资产 → 生成用例</div>
          </div>
        </el-col>
        <el-col :xs="24" :md="12">
          <div class="ctx-card" @click="$router.push('/requirement-parse')">
            <div class="ctx-title">需求文档解析</div>
            <div class="ctx-desc">上传需求文档 → 结构化解析 → AI 生成用例进用例库</div>
          </div>
        </el-col>
        <el-col :xs="24" :md="12">
          <div class="ctx-card" @click="$router.push('/analysis')">
            <div class="ctx-title">代码解析</div>
            <div class="ctx-desc">识别技术栈与接口，作为 AI 用例生成的输入</div>
          </div>
        </el-col>
        <el-col :xs="24" :md="12">
          <div class="ctx-card" @click="$router.push('/doc-review')">
            <div class="ctx-title">接口文档评审</div>
            <div class="ctx-desc">AI 评审接口质量，评审后到用例库生成用例</div>
          </div>
        </el-col>
      </el-row>
      <el-alert type="info" :closable="false" show-icon style="margin-top: 12px"
        title="提示：各解析页内选择本项目即可保持上下文；解析产物（接口/用例）自动归属本项目" />
    </el-card>

    <el-card shadow="hover" class="mt16">
      <template #header>
        <div class="card-row">
          <span>代码版本</span>
          <el-button size="small" :loading="loading" @click="loadVersions">刷新</el-button>
        </div>
      </template>
      <el-table :data="versions" v-loading="loading" stripe size="small">
        <el-table-column label="版本" min-width="120">
          <template #default="{ row }"><span class="mono">{{ row.version_id?.substring(0, 12) }}</span></template>
        </el-table-column>
        <el-table-column label="来源" width="90" align="center">
          <template #default="{ row }"><el-tag size="small" effect="plain">{{ row.source_type }}</el-tag></template>
        </el-table-column>
        <el-table-column prop="total_files" label="文件数" width="80" align="center" />
        <el-table-column label="说明" min-width="140" show-overflow-tooltip>
          <template #default="{ row }">{{ row.note || '—' }}</template>
        </el-table-column>
        <el-table-column label="时间" width="150">
          <template #default="{ row }">
            <span class="muted">{{ formatTime(row.created_at) }}</span>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-if="!loading && versions.length === 0"
        description="还没有代码版本 —— 到「项目管理」项目详情上传代码或从仓库拉取" :image-size="60" />
    </el-card>
  </div>
</template>

<script lang="ts">
/** 工作区·测试上下文（M4）—— 解析入口卡片 + 项目代码版本。 */
import { defineComponent } from 'vue'
import { projectCodeApi } from '@/api'

export default defineComponent({
  name: 'ProjectContext',
  data() {
    return {
      projectId: (this.$route.params.id as string) || '',
      versions: [] as any[],
      loading: false,
    }
  },
  methods: {
    formatTime(t?: string): string {
      if (!t) return '—'
      try {
        return new Date(t).toLocaleString('zh-CN')
      } catch {
        return t
      }
    },
    async loadVersions(): Promise<void> {
      this.loading = true
      try {
        const res: any = await projectCodeApi.listVersions(this.projectId)
        this.versions = res?.data?.list || []
      } catch {
        this.versions = []
      } finally {
        this.loading = false
      }
    },
  },
  mounted() {
    this.loadVersions()
  },
})
</script>

<style scoped>
.ctx-card {
  border: 1px solid #ebeef5;
  border-radius: 6px;
  padding: 14px 16px;
  margin-bottom: 12px;
  cursor: pointer;
  transition: all 0.2s;
}
.ctx-card:hover {
  border-color: #409eff;
  box-shadow: 0 2px 8px rgba(64, 158, 255, 0.1);
}
.ctx-title {
  font-weight: 600;
  color: #303133;
}
.ctx-desc {
  font-size: 12px;
  color: #909399;
  margin-top: 4px;
}
.card-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.mono {
  font-family: 'Courier New', Consolas, monospace;
  font-size: 12px;
}
.muted {
  font-size: 12px;
  color: #909399;
}
.mt16 {
  margin-top: 16px;
}
</style>
