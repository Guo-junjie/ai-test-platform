<template>
  <div class="ws-overview">
    <!-- 就绪度 -->
    <el-card shadow="hover">
      <template #header>项目就绪度</template>
      <div class="ready-grid">
        <div v-for="r in readiness" :key="r.key" class="ready-item" :class="{ ok: r.ok, missing: !r.ok }">
          <div class="ready-title">{{ r.title }}</div>
          <div class="ready-value">{{ r.value }}</div>
          <div class="ready-hint">{{ r.ok ? '就绪' : r.hint }}</div>
        </div>
      </div>
      <el-alert v-if="!allReady" type="warning" :closable="false" show-icon style="margin-top: 12px"
        title="存在未就绪项 —— 点击对应卡片的引导补齐后再执行计划" />
    </el-card>

    <el-row :gutter="16" class="mt16">
      <!-- 最近运行 -->
      <el-col :xs="24" :lg="14">
        <el-card shadow="hover">
          <template #header>
            <div class="card-row">
              <span>最近运行</span>
              <el-button size="small" text type="primary" @click="$router.push(`/projects/${projectId}/runs`)">
                运行中心
              </el-button>
            </div>
          </template>
          <el-table :data="recentRuns" v-loading="runsLoading" size="small" stripe @row-click="goRun">
            <el-table-column label="状态" width="90" align="center">
              <template #default="{ row }">
                <el-tag size="small" :type="statusType(row.status)">{{ statusLabel(row.status) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="进度" width="120">
              <template #default="{ row }">
                <el-progress :percentage="row.progress || 0" :stroke-width="8" />
              </template>
            </el-table-column>
            <el-table-column label="触发" width="90" align="center">
              <template #default="{ row }">{{ triggerLabel(row.trigger_type) }}</template>
            </el-table-column>
            <el-table-column label="时间" width="150">
              <template #default="{ row }">
                <span class="muted">{{ formatTime(row.created_at) }}</span>
              </template>
            </el-table-column>
          </el-table>
          <el-empty v-if="!runsLoading && recentRuns.length === 0" description="还没有运行记录 —— 去「测试计划」执行第一次回归"
            :image-size="60" />
        </el-card>
      </el-col>

      <!-- 质量与缺陷速览 -->
      <el-col :xs="24" :lg="10">
        <el-card shadow="hover">
          <template #header>质量速览</template>
          <div class="quality-row">
            <div class="q-item">
              <div class="q-num" :class="{ bad: openDefects > 0 }">{{ openDefects }}</div>
              <div class="q-label">待处理缺陷</div>
            </div>
            <div class="q-item">
              <div class="q-num">{{ caseCount }}</div>
              <div class="q-label">用例资产</div>
            </div>
            <div class="q-item">
              <div class="q-num">{{ publishedPlans }}</div>
              <div class="q-label">已发布计划</div>
            </div>
          </div>
          <div class="quality-links">
            <el-button size="small" plain @click="$router.push(`/defects?project_id=${projectId}`)">缺陷中心</el-button>
            <el-button size="small" plain @click="$router.push(`/coverage?project_id=${projectId}`)">代码覆盖率</el-button>
            <el-button size="small" plain @click="$router.push('/report')">测试报告</el-button>
          </div>
        </el-card>

        <el-card shadow="hover" class="mt16">
          <template #header>快捷操作</template>
          <div class="quick-actions">
            <el-button type="primary" @click="$router.push(`/projects/${projectId}/plans`)">执行测试计划</el-button>
            <el-button plain @click="$router.push('/doc-parser')">接口文档解析</el-button>
            <el-button plain @click="$router.push('/requirement-parse')">需求文档解析</el-button>
          </div>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script lang="ts">
/** 项目概览（M4）—— 就绪度 / 最近运行 / 质量速览，用户不离开工作区即可决策。 */
import { defineComponent } from 'vue'
import {
  caseApi,
  environmentApi,
  planApi,
  projectCodeApi,
  testRunApi,
} from '@/api'

const STATUS: Record<string, string> = {
  pending: '等待中', pulling: '拉取代码', analyzing: '解析代码', generating: '生成用例',
  executing: '执行中', analyzing_defects: '分析缺陷', reporting: '生成报告',
  completed: '已完成', failed: '失败', cancelled: '已取消',
}
const TRIGGERS: Record<string, string> = {
  manual: '手动', schedule: '定时', webhook: 'CI/Webhook', retry: '重试',
}

export default defineComponent({
  name: 'ProjectOverview',
  data() {
    return {
      projectId: (this.$route.params.id as string) || '',
      codeVersions: [] as any[],
      environments: [] as any[],
      plans: [] as any[],
      caseCount: 0,
      recentRuns: [] as any[],
      runsLoading: false,
      openDefects: 0,
    }
  },
  computed: {
    publishedEnvs(): number {
      return this.environments.filter((e: any) => e.status === 'published').length
    },
    publishedPlans(): number {
      return this.plans.filter((p: any) => (p.published_revision || 0) > 0).length
    },
    readiness(): Array<{ key: string; title: string; value: string; ok: boolean; hint: string }> {
      return [
        {
          key: 'code', title: '代码版本',
          value: `${this.codeVersions.length} 个`,
          ok: this.codeVersions.length > 0,
          hint: '到「测试上下文」上传或拉取代码',
        },
        {
          key: 'env', title: '已发布环境',
          value: `${this.publishedEnvs} 个`,
          ok: this.publishedEnvs > 0,
          hint: '到「测试上下文 → 环境」创建并发布',
        },
        {
          key: 'cases', title: '用例资产',
          value: `${this.caseCount} 条`,
          ok: this.caseCount > 0,
          hint: '接口/需求文档解析生成，或流水线自动生成',
        },
        {
          key: 'plan', title: '已发布计划',
          value: `${this.publishedPlans} 个`,
          ok: this.publishedPlans > 0,
          hint: '到「测试计划」创建并发布',
        },
      ]
    },
    allReady(): boolean {
      return this.readiness.every((r) => r.ok)
    },
  },
  methods: {
    statusType(s: string): string {
      return s === 'completed' ? 'success' : s === 'failed' ? 'danger' : 'warning'
    },
    statusLabel(s: string): string {
      return STATUS[s] || s
    },
    triggerLabel(t?: string): string {
      return TRIGGERS[t || ''] || '手动'
    },
    formatTime(t?: string): string {
      if (!t) return '—'
      try {
        return new Date(t).toLocaleString('zh-CN')
      } catch {
        return t
      }
    },
    goRun(row: any): void {
      // 运行详情在测试运行页的任务详情对话框中呈现
      this.$router.push('/test-run')
    },
    async loadAll(): Promise<void> {
      const pid = this.projectId
      // 并行拉取各项就绪数据（单项失败不影响其它）
      const jobs = [
        projectCodeApi.listVersions(pid).then((res: any) => { this.codeVersions = res?.data?.list || [] }).catch(() => {}),
        environmentApi.list(pid).then((res: any) => { this.environments = res?.data?.list || [] }).catch(() => {}),
        planApi.list({ project_id: pid, page: 1, page_size: 100 }).then((res: any) => {
          this.plans = res?.data?.list || []
        }).catch(() => {}),
        caseApi.list({ project_id: pid, page: 1, page_size: 1 }).then((res: any) => {
          this.caseCount = res?.data?.total ?? (res?.data?.list?.length || 0)
        }).catch(() => {}),
        testRunApi.getList({ project_id: pid }).then((res: any) => {
          this.recentRuns = (res?.data?.list || []).slice(0, 6)
        }).catch(() => {}),
      ]
      this.runsLoading = true
      await Promise.all(jobs)
      this.runsLoading = false
      // 待处理缺陷
      try {
        const res: any = await (await import('@/api')).default.get('/defects', {
          params: { project_id: pid, status_code: 'open', page: 1, page_size: 1 },
        })
        this.openDefects = res?.data?.total ?? 0
      } catch {
        this.openDefects = 0
      }
    },
  },
  mounted() {
    this.loadAll()
  },
})
</script>

<style scoped>
.ready-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
}
.ready-item {
  border: 1px solid #ebeef5;
  border-radius: 6px;
  padding: 12px;
  text-align: center;
}
.ready-item.ok {
  border-color: #b3e19d;
  background: #f9fff6;
}
.ready-item.missing {
  border-color: #f3d19e;
  background: #fffaf0;
}
.ready-title {
  font-size: 12px;
  color: #909399;
}
.ready-value {
  font-size: 20px;
  font-weight: 700;
  margin: 4px 0;
}
.ready-hint {
  font-size: 11px;
  color: #c0c4cc;
}
.card-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.quality-row {
  display: flex;
  justify-content: space-around;
  text-align: center;
}
.q-num {
  font-size: 24px;
  font-weight: 700;
}
.q-num.bad {
  color: #f56c6c;
}
.q-label {
  font-size: 12px;
  color: #909399;
  margin-top: 4px;
}
.quality-links,
.quick-actions {
  display: flex;
  gap: 8px;
  margin-top: 12px;
  flex-wrap: wrap;
}
.muted {
  font-size: 12px;
  color: #909399;
}
.mt16 {
  margin-top: 16px;
}
</style>
