<template>
  <div>
    <!-- 工具栏：关键字搜索 + method 过滤 -->
    <div v-if="!hideToolbar" class="toolbar">
      <el-input
        v-model="keyword"
        placeholder="搜索 path / summary"
        clearable
        style="width: 260px"
      />
      <el-select
        v-model="methodFilter"
        placeholder="方法"
        clearable
        multiple
        collapse-tags
        style="width: 220px"
      >
        <el-option v-for="m in methods" :key="m" :label="m" :value="m" />
      </el-select>
      <span class="count">共 {{ filtered.length }} 个接口</span>
    </div>

    <el-table
      v-loading="loading"
      :data="filtered"
      border
      stripe
      :max-height="maxHeight"
      @selection-change="handleSelectionChange"
    >
      <el-table-column v-if="selectable" type="selection" width="46" />
      <el-table-column label="方法" width="90">
        <template #default="{ row }">
          <el-tag :type="methodType(row.method)" size="small" effect="dark">
            {{ row.method }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="path" label="路径" min-width="220" show-overflow-tooltip />
      <el-table-column prop="summary" label="说明" min-width="160" show-overflow-tooltip />
      <el-table-column label="参数数" width="80" align="center">
        <template #default="{ row }">{{ (row.params || []).length }}</template>
      </el-table-column>
      <el-table-column label="响应数" width="80" align="center">
        <template #default="{ row }">{{ (row.responses || []).length }}</template>
      </el-table-column>
      <el-table-column label="认证" width="70" align="center">
        <template #default="{ row }">
          <el-tag v-if="row.auth_required" type="danger" size="small">需鉴权</el-tag>
          <span v-else class="muted">—</span>
        </template>
      </el-table-column>
      <el-table-column label="置信度" width="120" v-if="showConfidence">
        <template #default="{ row }">
          <el-progress
            :percentage="Math.round((row.confidence || 0) * 100)"
            :stroke-width="10"
            :show-text="true"
            size="small"
          />
        </template>
      </el-table-column>
      <el-table-column label="操作" width="70" fixed="right">
        <template #default="{ row }">
          <el-button size="small" text type="primary" @click="openDetail(row)">详情</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-drawer v-model="detailVisible" title="接口详情" size="46%">
      <template v-if="current">
        <el-descriptions :column="1" border>
          <el-descriptions-item label="方法">{{ current.method }}</el-descriptions-item>
          <el-descriptions-item label="路径">{{ current.path }}</el-descriptions-item>
          <el-descriptions-item label="说明">{{ current.summary || '—' }}</el-descriptions-item>
          <el-descriptions-item label="描述">{{ current.description || '—' }}</el-descriptions-item>
          <el-descriptions-item label="鉴权">
            {{ current.auth_required ? (current.auth_type || '需鉴权') : '无需鉴权' }}
          </el-descriptions-item>
        </el-descriptions>

        <h4>请求参数</h4>
        <el-table :data="current.params || []" size="small" border>
          <el-table-column prop="name" label="名称" />
          <el-table-column prop="in" label="位置" width="90" />
          <el-table-column prop="type" label="类型" width="90" />
          <el-table-column prop="required" label="必填" width="70" align="center">
            <template #default="{ row }">
              <el-tag :type="row.required ? 'danger' : 'info'" size="small">
                {{ row.required ? '是' : '否' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="description" label="说明" show-overflow-tooltip />
        </el-table>

        <h4>请求体</h4>
        <pre class="json-box">{{ pretty(current.request_body) }}</pre>

        <h4>响应定义</h4>
        <el-table :data="current.responses || []" size="small" border>
          <el-table-column prop="status_code" label="状态码" width="90" />
          <el-table-column prop="description" label="说明" show-overflow-tooltip />
        </el-table>
      </template>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'

const props = defineProps<{
  endpoints?: any[]
  selectable?: boolean
  modelValue?: string[]
  loading?: boolean
  maxHeight?: number
  hideToolbar?: boolean
  showConfidence?: boolean
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', v: string[]): void
}>()

const methods = ['GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'OPTIONS', 'HEAD']
const keyword = ref('')
const methodFilter = ref<string[]>([])
const detailVisible = ref(false)
const current = ref<any>(null)

function keyOf(e: any): string {
  return `${String(e.method || '').toUpperCase()} ${e.path || ''}`
}

const rows = computed(() =>
  (props.endpoints || []).map((e) => ({ ...e, _key: keyOf(e) })),
)

const filtered = computed(() => {
  const kw = keyword.value.trim().toLowerCase()
  const mf = methodFilter.value.map((m) => m.toUpperCase())
  return rows.value.filter((e) => {
    if (mf.length && !mf.includes(String(e.method || '').toUpperCase())) return false
    if (kw) {
      const hay = `${e.path || ''} ${e.summary || ''}`.toLowerCase()
      if (!hay.includes(kw)) return false
    }
    return true
  })
})

function methodType(method: string): any {
  switch (String(method || '').toUpperCase()) {
    case 'GET':
      return 'success'
    case 'POST':
      return 'warning'
    case 'PUT':
      return 'primary'
    case 'DELETE':
      return 'danger'
    case 'PATCH':
      return 'info'
    default:
      return 'info'
  }
}

function handleSelectionChange(selectedRows: any[]) {
  emit(
    'update:modelValue',
    selectedRows.map((r) => r._key),
  )
}

function openDetail(row: any) {
  current.value = row
  detailVisible.value = true
}

function pretty(obj: any): string {
  if (obj === null || obj === undefined) return '—'
  try {
    return JSON.stringify(obj, null, 2)
  } catch {
    return String(obj)
  }
}
</script>

<style scoped>
.toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}
.count {
  color: #909399;
  font-size: 13px;
}
.muted {
  color: #c0c4cc;
}
.json-box {
  background: #f5f7fa;
  border-radius: 4px;
  padding: 10px;
  font-size: 12px;
  max-height: 240px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-all;
}
h4 {
  margin: 16px 0 8px;
  font-size: 14px;
  color: #303133;
}
</style>
