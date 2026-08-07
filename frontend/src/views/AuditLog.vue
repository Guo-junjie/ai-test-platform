<template>
  <div class="audit-log-page">
    <!-- 统计卡片 -->
    <el-row :gutter="16">
      <el-col :span="8">
        <el-card shadow="hover" class="stat-card">
          <div class="stat-value">{{ stats.total_logs ?? 0 }}</div>
          <div class="stat-label">近 {{ stats.days ?? 30 }} 天日志总数</div>
        </el-card>
      </el-col>
      <el-col :span="8">
        <el-card shadow="hover" class="stat-card">
          <div class="stat-value">{{ Object.keys(stats.by_action || {}).length }}</div>
          <div class="stat-label">操作类型数</div>
        </el-card>
      </el-col>
      <el-col :span="8">
        <el-card shadow="hover" class="stat-card">
          <div class="stat-value">{{ (stats.top_users || []).length }}</div>
          <div class="stat-label">活跃用户数</div>
        </el-card>
      </el-col>
    </el-row>

    <el-card shadow="hover" style="margin-top: 20px;">
      <template #header>
        <div class="card-header">
          <span>审计日志</span>
        </div>
      </template>

      <!-- 筛选栏 -->
      <div class="filter-bar">
        <el-input
          v-model="filters.action"
          placeholder="操作类型"
          style="width: 160px;"
          clearable
        />
        <el-input
          v-model="filters.resource_type"
          placeholder="资源类型"
          style="width: 160px;"
          clearable
        />
        <el-date-picker
          v-model="dateRange"
          type="daterange"
          range-separator="至"
          start-placeholder="开始日期"
          end-placeholder="结束日期"
          style="width: 260px;"
        />
        <el-button type="primary" @click="search">查询</el-button>
        <el-button @click="resetFilters">重置</el-button>
      </div>

      <!-- 日志表格 -->
      <el-table :data="logs" v-loading="loading" style="width: 100%; margin-top: 16px;">
        <el-table-column prop="created_at" label="时间" width="180">
          <template #default="{ row }">
            {{ formatTime(row.created_at) }}
          </template>
        </el-table-column>
        <el-table-column prop="username" label="用户" width="110">
          <template #default="{ row }">
            <el-tag size="small">{{ row.username }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="action" label="操作" min-width="180">
          <template #default="{ row }">
            <code class="action-code">{{ row.action }}</code>
          </template>
        </el-table-column>
        <el-table-column prop="resource_type" label="资源类型" width="120" />
        <el-table-column prop="resource_id" label="资源 ID" min-width="160" show-overflow-tooltip />
        <el-table-column prop="ip_address" label="IP 地址" width="140" />
        <el-table-column label="详情" min-width="200">
          <template #default="{ row }">
            <el-popover placement="left" :width="300" trigger="click">
              <template #reference>
                <el-button link type="primary" size="small">查看</el-button>
              </template>
              <pre class="detail-json">{{ JSON.stringify(row.details || {}, null, 2) }}</pre>
            </el-popover>
          </template>
        </el-table-column>
      </el-table>

      <!-- 分页 -->
      <el-pagination
        v-if="total > pageSize"
        background
        layout="prev, pager, next, total"
        :total="total"
        :page-size="pageSize"
        v-model:current-page="page"
        @current-change="loadLogs"
        style="margin-top: 16px; justify-content: flex-end;"
      />
      <el-empty v-else-if="!loading && logs.length === 0" description="暂无审计日志" />
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { auditApi } from '@/api'

const loading = ref(false)
const logs = ref<any[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const dateRange = ref<[string, string] | null>(null)

const stats = ref<any>({})

const filters = reactive({
  action: '',
  resource_type: '',
  start_date: '',
  end_date: '',
})

function formatTime(iso: string | null): string {
  if (!iso) return '--'
  try {
    const d = new Date(iso)
    return d.toLocaleString('zh-CN', { hour12: false })
  } catch {
    return iso || '--'
  }
}

async function loadStats() {
  try {
    const res: any = await auditApi.getStatistics(30)
    stats.value = res.data || {}
  } catch {
    /* 忽略 */
  }
}

async function loadLogs() {
  loading.value = true
  try {
    const res: any = await auditApi.list({
      action: filters.action || undefined,
      resource_type: filters.resource_type || undefined,
      start_date: filters.start_date || undefined,
      end_date: filters.end_date || undefined,
      page: page.value,
      page_size: pageSize.value,
    })
    const d = res.data || {}
    logs.value = d.list || []
    total.value = d.total || 0
  } catch {
    logs.value = []
  } finally {
    loading.value = false
  }
}

function search() {
  if (dateRange.value && dateRange.value.length === 2) {
    filters.start_date = dateRange.value[0] || ''
    filters.end_date = dateRange.value[1] || ''
  } else {
    filters.start_date = ''
    filters.end_date = ''
  }
  page.value = 1
  loadLogs()
}

function resetFilters() {
  filters.action = ''
  filters.resource_type = ''
  filters.start_date = ''
  filters.end_date = ''
  dateRange.value = null
  page.value = 1
  loadLogs()
}

onMounted(() => {
  loadStats()
  loadLogs()
})
</script>

<style scoped>
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.stat-card {
  text-align: center;
  padding: 8px 0;
}

.stat-value {
  font-size: 28px;
  font-weight: 700;
  color: #409eff;
}

.stat-label {
  font-size: 13px;
  color: #909399;
  margin-top: 4px;
}

.filter-bar {
  display: flex;
  gap: 12px;
  align-items: center;
  flex-wrap: wrap;
}

.action-code {
  background: #f4f4f5;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 12px;
}

.detail-json {
  margin: 0;
  max-height: 300px;
  overflow-y: auto;
  font-size: 12px;
  line-height: 1.5;
}
</style>
