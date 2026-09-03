<template>
  <div class="defects-page">
    <!-- 统计概览 -->
    <el-card shadow="hover">
      <div class="stats-row">
        <div class="stat-item" v-for="s in severityStats" :key="s.key">
          <el-tag :type="s.tag" effect="dark" size="large">{{ s.label }}</el-tag>
          <span class="stat-num">{{ s.count }}</span>
        </div>
        <div class="stat-sep" />
        <div class="stat-item" v-for="s in statusStats" :key="s.key">
          <span class="stat-label">{{ s.label }}</span>
          <span class="stat-num small">{{ s.count }}</span>
        </div>
      </div>
    </el-card>

    <!-- 过滤与列表 -->
    <el-card shadow="hover">
      <template #header>
        <div class="card-header">
          <span>缺陷列表</span>
          <div class="header-actions">
            <el-select v-model="filters.project_id" placeholder="全部项目" clearable style="width: 160px" @change="reload">
              <el-option v-for="p in projects" :key="p.id" :label="p.name" :value="p.id" />
            </el-select>
            <el-select v-model="filters.severity" placeholder="全部等级" clearable style="width: 120px" @change="reload">
              <el-option v-for="(l, k) in SEVERITY" :key="k" :label="l" :value="k" />
            </el-select>
            <el-select v-model="filters.status_code" placeholder="全部状态" clearable style="width: 120px" @change="reload">
              <el-option v-for="(l, k) in STATUS" :key="k" :label="l" :value="k" />
            </el-select>
            <el-select v-model="filters.defect_type" placeholder="全部类型" clearable style="width: 130px" @change="reload">
              <el-option v-for="(l, k) in TYPES" :key="k" :label="l" :value="k" />
            </el-select>
            <el-input v-model="filters.q" placeholder="搜索标题/描述" clearable style="width: 180px"
              @keyup.enter="reload" @clear="reload" />
            <el-button type="primary" :disabled="!canCreate" @click="openCreate">登记缺陷</el-button>
          </div>
        </div>
      </template>

      <el-table :data="list" v-loading="loading" stripe size="small">
        <el-table-column label="等级" width="90">
          <template #default="{ row }">
            <el-tag :type="sevTag(row.severity)" effect="dark" size="small">{{ row.severity }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="title" label="标题" min-width="240" show-overflow-tooltip />
        <el-table-column label="项目" width="130" show-overflow-tooltip>
          <template #default="{ row }">{{ row.project_name || '—' }}</template>
        </el-table-column>
        <el-table-column label="类型" width="100">
          <template #default="{ row }">{{ row.defect_type_label || row.defect_type }}</template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="statusTag(row.status_code)" size="small">{{ row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="根因" width="70">
          <template #default="{ row }">
            <el-tag v-if="row.root_cause" size="small" type="info" effect="plain">AI</el-tag>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column label="发现时间" width="160">
          <template #default="{ row }">{{ fmt(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="200" fixed="right">
          <template #default="{ row }">
            <el-button size="small" text type="primary" @click="openDetail(row)">详情</el-button>
            <el-dropdown v-if="nextStatuses(row.status_code).length" @command="(s: string) => changeStatus(row, s)" trigger="click">
              <el-button size="small" text type="warning">流转</el-button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item v-for="s in nextStatuses(row.status_code)" :key="s" :command="s">
                    → {{ STATUS[s] }}
                  </el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
            <el-button size="small" text type="danger" :disabled="!canDelete" @click="remove(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>

      <div class="pagination-wrapper" v-if="total > pageSize">
        <el-pagination layout="total, prev, pager, next" :total="total"
          :current-page="page" :page-size="pageSize" @current-change="onPage" />
      </div>
    </el-card>

    <!-- 详情抽屉 -->
    <el-drawer v-model="detailVisible" title="缺陷详情" size="480px">
      <template v-if="detail">
        <h3>{{ detail.title }}</h3>
        <el-descriptions :column="1" border size="small" style="margin: 12px 0">
          <el-descriptions-item label="等级">{{ detail.severity }}（{{ detail.severity_label }}）</el-descriptions-item>
          <el-descriptions-item label="类型">{{ detail.defect_type_label }}</el-descriptions-item>
          <el-descriptions-item label="状态">{{ detail.status }}</el-descriptions-item>
          <el-descriptions-item label="项目">{{ detail.project_name || '—' }}</el-descriptions-item>
          <el-descriptions-item label="关联任务">
            <span class="mono">{{ detail.test_run_id?.substring(0, 8) || '手动登记' }}</span>
          </el-descriptions-item>
        </el-descriptions>
        <h4>描述</h4>
        <p class="pre">{{ detail.description }}</p>
        <template v-if="detail.reproduce_steps?.length">
          <h4>复现步骤 / 处理记录</h4>
          <ol><li v-for="(s, i) in detail.reproduce_steps" :key="i" class="pre">{{ s }}</li></ol>
        </template>
        <template v-if="detail.root_cause">
          <h4>AI 根因分析</h4>
          <p class="pre">{{ detail.root_cause }}</p>
        </template>
        <template v-if="detail.fix_suggestion">
          <h4>修复建议</h4>
          <p class="pre">{{ detail.fix_suggestion }}</p>
        </template>
      </template>
    </el-drawer>

    <!-- 登记缺陷 -->
    <el-dialog v-model="createVisible" title="登记缺陷" width="560px">
      <el-form label-width="90px">
        <el-form-item label="项目" required>
          <el-select v-model="form.project_id" style="width: 100%">
            <el-option v-for="p in projects" :key="p.id" :label="p.name" :value="p.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="标题" required>
          <el-input v-model="form.title" placeholder="一句话描述问题" />
        </el-form-item>
        <el-form-item label="等级">
          <el-select v-model="form.severity" style="width: 100%">
            <el-option v-for="(l, k) in SEVERITY" :key="k" :label="`${k} ${l}`" :value="k" />
          </el-select>
        </el-form-item>
        <el-form-item label="类型">
          <el-select v-model="form.defect_type" style="width: 100%">
            <el-option v-for="(l, k) in TYPES" :key="k" :label="l" :value="k" />
          </el-select>
        </el-form-item>
        <el-form-item label="描述" required>
          <el-input v-model="form.description" type="textarea" :rows="4" placeholder="现象、期望、实际、影响范围" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="submitCreate">提交</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import api, { projectApi } from '@/api'
import { useAuthStore } from '@/stores'

const SEVERITY: Record<string, string> = { P0: '致命', P1: '严重', P2: '一般', P3: '轻微' }
const STATUS: Record<string, string> = { open: '待处理', in_fix: '修复中', verified: '已验证', closed: '已关闭', rejected: '已驳回' }
const TYPES: Record<string, string> = {
  business: '业务缺陷', program: '程序缺陷', performance: '性能缺陷',
  integration: '集成缺陷', security: '安全缺陷',
}
const TRANSITIONS: Record<string, string[]> = {
  open: ['in_fix', 'rejected', 'closed'],
  in_fix: ['verified', 'open', 'rejected'],
  verified: ['closed', 'open'],
  closed: [],
  rejected: ['open'],
}

const authStore = useAuthStore()
const role = computed(() => authStore.role)
const canCreate = computed(() => !['viewer', 'auditor'].includes(role.value))
const canDelete = computed(() => ['super_admin', 'admin', 'test_manager'].includes(role.value))

const projects = ref<any[]>([])
const list = ref<any[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 20
const loading = ref(false)
const stats = ref<any>({ by_severity: {}, by_status: {} })
const filters = reactive<any>({ project_id: '', severity: '', status_code: '', defect_type: '', q: '' })

const detailVisible = ref(false)
const detail = ref<any>(null)
const createVisible = ref(false)
const creating = ref(false)
const form = reactive<any>({ project_id: '', title: '', severity: 'P2', defect_type: 'business', description: '' })

const severityStats = computed(() => [
  { key: 'P0', label: 'P0 致命', count: stats.value.by_severity?.P0 ?? 0, tag: 'danger' },
  { key: 'P1', label: 'P1 严重', count: stats.value.by_severity?.P1 ?? 0, tag: 'warning' },
  { key: 'P2', label: 'P2 一般', count: stats.value.by_severity?.P2 ?? 0, tag: 'primary' },
  { key: 'P3', label: 'P3 轻微', count: stats.value.by_severity?.P3 ?? 0, tag: 'info' },
])
const statusStats = computed(() =>
  Object.entries(STATUS).map(([k, label]) => ({ key: k, label, count: stats.value.by_status?.[k] ?? 0 })),
)

function sevTag(s: string): string {
  return { P0: 'danger', P1: 'warning', P2: 'primary', P3: 'info' }[s] || 'info'
}
function statusTag(s: string): string {
  return { open: 'danger', in_fix: 'warning', verified: 'primary', closed: 'success', rejected: 'info' }[s] || 'info'
}
function nextStatuses(s: string): string[] {
  return TRANSITIONS[s] || []
}
function fmt(t: string): string {
  return t ? new Date(t).toLocaleString('zh-CN', { hour12: false }) : '—'
}

async function loadProjects() {
  try {
    const res: any = await projectApi.getList()
    const d = res?.data ?? res
    projects.value = Array.isArray(d) ? d : d?.list || d?.items || []
  } catch { projects.value = [] }
}

async function load() {
  loading.value = true
  try {
    const params: any = { page: page.value, page_size: pageSize }
    for (const k of Object.keys(filters)) if (filters[k]) params[k] = filters[k]
    const res: any = await api.get('/defects', { params })
    list.value = res?.data?.list ?? []
    total.value = res?.data?.total ?? 0
    stats.value = res?.data?.stats ?? { by_severity: {}, by_status: {} }
  } catch { list.value = [] } finally { loading.value = false }
}

function reload() { page.value = 1; void load() }
function onPage(p: number) { page.value = p; void load() }

function openDetail(row: any) {
  detail.value = row
  detailVisible.value = true
}

function openCreate() {
  form.project_id = filters.project_id || ''
  form.title = ''
  form.description = ''
  form.severity = 'P2'
  form.defect_type = 'business'
  createVisible.value = true
}

async function submitCreate() {
  if (!form.project_id || !form.title.trim() || !form.description.trim()) {
    ElMessage.warning('项目、标题、描述必填')
    return
  }
  try {
    creating.value = true
    const res: any = await api.post('/defects', {
      project_id: form.project_id,
      title: form.title.trim(),
      description: form.description.trim(),
      severity: form.severity,
      defect_type: form.defect_type,
    })
    if (res?.code === 0) {
      ElMessage.success('缺陷已登记')
      createVisible.value = false
      void load()
    } else {
      ElMessage.error(res?.message || '创建失败')
    }
  } finally { creating.value = false }
}

async function changeStatus(row: any, next: string) {
  let note = ''
  try {
    const r = await ElMessageBox.prompt(`流转到「${STATUS[next]}」，可填写备注`, '状态流转', {
      inputValue: '', confirmButtonText: '确定', cancelButtonText: '取消',
    })
    note = r.value || ''
  } catch { return }
  try {
    const res: any = await api.patch(`/defects/${row.id}/status`, { status: next, note })
    if (res?.code === 0) {
      ElMessage.success(`已流转到 ${STATUS[next]}`)
      void load()
    } else {
      ElMessage.error(res?.detail || res?.message || '流转失败')
    }
  } catch { /* 拦截器已提示 */ }
}

async function remove(row: any) {
  try {
    await ElMessageBox.confirm(`确定删除缺陷「${row.title}」？`, '删除确认', { type: 'warning' })
  } catch { return }
  try {
    const res: any = await api.delete(`/defects/${row.id}`)
    if (res?.code === 0) { ElMessage.success('已删除'); void load() }
  } catch { /* */ }
}

onMounted(() => {
  void loadProjects()
  void load()
})
</script>

<style scoped>
.stats-row { display: flex; align-items: center; gap: 20px; flex-wrap: wrap; }
.stat-item { display: flex; align-items: center; gap: 8px; }
.stat-num { font-size: 20px; font-weight: 700; }
.stat-num.small { font-size: 15px; font-weight: 600; }
.stat-label { color: #909399; font-size: 13px; }
.stat-sep { width: 1px; height: 22px; background: #dcdfe6; }
.card-header { display: flex; justify-content: space-between; align-items: center; }
.header-actions { display: flex; gap: 8px; flex-wrap: wrap; }
.pagination-wrapper { display: flex; justify-content: center; margin-top: 14px; }
.muted { color: #c0c4cc; }
.mono { font-family: Consolas, monospace; }
.pre { white-space: pre-wrap; word-break: break-word; font-size: 13px; color: #303133; }
h4 { margin: 14px 0 6px; color: #606266; }
</style>
