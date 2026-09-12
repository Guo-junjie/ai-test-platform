<template>
  <div class="ws-runs">
    <el-card shadow="hover">
      <template #header>
        <div class="card-row">
          <span>运行中心 —— 本项目全部测试运行</span>
          <el-button size="small" :loading="loading" @click="loadRuns">刷新</el-button>
        </div>
      </template>

      <el-table :data="runs" v-loading="loading" stripe row-key="id">
        <el-table-column type="expand">
          <template #default="{ row }">
            <div class="expand-body" v-loading="row._eventsLoading">
              <template v-if="row._events && row._events.length > 0">
                <el-timeline style="padding-left: 8px">
                  <el-timeline-item
                    v-for="e in row._events"
                    :key="e.sequence"
                    :timestamp="formatTime(e.created_at)"
                    :type="e.event_type === 'run.completed' ? 'success' : e.event_type === 'run.failed' ? 'danger' : 'primary'"
                  >
                    <b>{{ e.event_type }}</b>
                    <span v-if="e.payload && e.payload.error" class="muted" style="margin-left: 6px">{{ e.payload.error }}</span>
                  </el-timeline-item>
                </el-timeline>
              </template>
              <span v-else-if="!row._eventsLoading" class="muted">暂无事件（历史运行，证据可能不完整）</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100" align="center">
          <template #default="{ row }">
            <el-tag size="small" :type="statusType(row.status)">{{ statusLabel(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="进度" width="140">
          <template #default="{ row }">
            <el-progress :percentage="row.progress || 0" :stroke-width="8" />
          </template>
        </el-table-column>
        <el-table-column label="触发" width="100" align="center">
          <template #default="{ row }">{{ triggerLabel(row.trigger_type) }}</template>
        </el-table-column>
        <el-table-column label="当前步骤" min-width="140" show-overflow-tooltip>
          <template #default="{ row }">{{ statusLabel(row.current_step || row.status) }}</template>
        </el-table-column>
        <el-table-column label="错误" min-width="160" show-overflow-tooltip>
          <template #default="{ row }">
            <span v-if="row.error_message" class="err">{{ row.error_message }}</span>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column label="时间" width="150">
          <template #default="{ row }">
            <span class="muted">{{ formatTime(row.created_at) }}</span>
          </template>
        </el-table-column>
      </el-table>

      <el-empty v-if="!loading && runs.length === 0"
        description="还没有运行记录 —— 到「测试计划」执行第一次回归" :image-size="70" />
    </el-card>
  </div>
</template>

<script lang="ts">
/** 工作区·运行中心（M4 + M3 事件时间线）—— 每条 Run 展开即见执行时间线。 */
import { defineComponent } from 'vue'
import { testRunApi } from '@/api'

const STATUS: Record<string, string> = {
  pending: '等待中', pulling: '拉取代码', analyzing: '解析代码', generating: '生成用例',
  executing: '执行中', analyzing_defects: '分析缺陷', reporting: '生成报告',
  completed: '已完成', failed: '失败', cancelled: '已取消',
}
const TRIGGERS: Record<string, string> = {
  manual: '手动', schedule: '定时', webhook: 'CI/Webhook', retry: '重试',
}

export default defineComponent({
  name: 'ProjectRuns',
  data() {
    return {
      projectId: (this.$route.params.id as string) || '',
      runs: [] as any[],
      loading: false,
    }
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
    async loadRuns(): Promise<void> {
      this.loading = true
      try {
        const res: any = await testRunApi.getList({ project_id: this.projectId })
        this.runs = (res?.data?.list || []).map((r: any) => ({ ...r, _events: null, _eventsLoading: false }))
      } catch {
        this.runs = []
      } finally {
        this.loading = false
      }
    },
    async loadEvents(row: any): Promise<void> {
      if (row._events) return
      row._eventsLoading = true
      try {
        const res: any = await testRunApi.getEvents(row.id)
        row._events = res?.data?.list || []
      } catch {
        row._events = []
      } finally {
        row._eventsLoading = false
      }
    },
  },
  watch: {
    runs: {
      handler(list: any[]) {
        // 展开行懒加载事件
        list.forEach((r) => {
          if (r._eventsLoaded) return
          r._eventsLoaded = true
          this.loadEvents(r)
        })
      },
      deep: false,
    },
  },
  mounted() {
    this.loadRuns()
  },
})
</script>

<style scoped>
.card-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.expand-body {
  padding: 8px 24px;
}
.muted {
  font-size: 12px;
  color: #909399;
}
.err {
  font-size: 12px;
  color: #f56c6c;
}
</style>
