<template>
  <div class="knowledge-base">
    <!-- 顶部状态卡片 -->
    <el-card shadow="hover" class="status-card">
      <template #header>
        <div class="card-header">
          <span>知识库状态概览</span>
          <div class="header-actions">
            <el-tooltip :content="rebuildTooltip" :disabled="!rebuildTooltip" placement="top">
              <el-button
                type="warning"
                :loading="rebuildLoading"
                :disabled="rebuildDisabled"
                @click="handleRebuild"
              >
                一键重建
              </el-button>
            </el-tooltip>
            <el-button :disabled="rebuildLoading" @click="loadStatus">刷新</el-button>
          </div>
        </div>
      </template>

      <el-alert
        v-if="!status.enabled"
        type="warning"
        :closable="false"
        show-icon
        title="知识库检索当前未启用"
        description="需在后端设置 KB_RAG_ENABLED=true 后重启生效。"
        style="margin-bottom: 16px"
      />

      <el-row :gutter="16">
        <el-col :xs="12" :sm="8" :md="6">
          <div class="stat-item">
            <div class="stat-label">RAG 开关</div>
            <el-tag :type="status.enabled ? 'success' : 'info'" effect="dark">
              {{ status.enabled ? '已启用' : '未启用' }}
            </el-tag>
          </div>
        </el-col>
        <el-col :xs="12" :sm="8" :md="6">
          <div class="stat-item">
            <div class="stat-label">术语总数</div>
            <div class="stat-value">{{ status.term_count }}</div>
          </div>
        </el-col>
        <el-col :xs="12" :sm="8" :md="6">
          <div class="stat-item">
            <div class="stat-label">嵌入模型</div>
            <div class="stat-value text-ellipsis" :title="status.embedding_model_id || '未配置'">
              {{ status.embedding_model_id || '未配置' }}
            </div>
          </div>
        </el-col>
        <el-col :xs="12" :sm="8" :md="6">
          <div class="stat-item">
            <div class="stat-label">重建状态</div>
            <el-tag :type="status.state === 'running' ? 'warning' : 'success'" effect="plain">
              {{ status.state === 'running' ? '重建中…' : '空闲' }}
            </el-tag>
          </div>
        </el-col>
        <el-col :xs="24" :md="12">
          <div class="stat-item">
            <div class="stat-label">上次重建时间</div>
            <div class="stat-value-sm">{{ formatTime(status.last_rebuild) }}</div>
          </div>
        </el-col>
      </el-row>

      <el-divider content-position="left">切片数（按知识库类型）</el-divider>
      <el-row :gutter="16">
        <el-col v-for="item in chunkCountList" :key="item.key" :xs="12" :sm="6" :md="6">
          <div class="chunk-box">
            <div class="chunk-count">{{ item.count }}</div>
            <div class="chunk-label">{{ item.label }}</div>
          </div>
        </el-col>
      </el-row>
    </el-card>

    <!-- 术语表维护 -->
    <el-card shadow="hover" class="term-card">
      <template #header>
        <div class="card-header">
          <span>术语表维护</span>
          <div class="header-actions">
            <el-input
              v-model="searchKeyword"
              placeholder="搜索术语 / 含义"
              clearable
              style="width: 220px"
              @keyup.enter="handleTermSearch"
              @clear="handleTermSearch"
            />
            <el-tooltip :content="termTooltip" :disabled="canManageTerm" placement="top">
              <span>
                <el-button type="primary" :disabled="!canManageTerm" @click="openCreate">
                  新建术语
                </el-button>
              </span>
            </el-tooltip>
          </div>
        </div>
      </template>

      <el-table
        :data="terms"
        v-loading="termsLoading"
        size="small"
        border
        empty-text="暂无术语"
        style="width: 100%"
      >
        <el-table-column prop="term" label="术语" min-width="140" />
        <el-table-column label="别名" min-width="180">
          <template #default="{ row }">
            <el-tag
              v-for="alias in (row.aliases || [])"
              :key="alias"
              size="small"
              type="info"
              effect="plain"
              style="margin-right: 4px"
            >
              {{ alias }}
            </el-tag>
            <span v-if="!row.aliases || !row.aliases.length" class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column prop="technical_meaning" label="技术含义" min-width="200" show-overflow-tooltip />
        <el-table-column prop="domain" label="领域" width="120" />
        <el-table-column label="更新时间" width="170">
          <template #default="{ row }">
            {{ formatTime(row.updated_at) }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="150" fixed="right">
          <template #default="{ row }">
            <el-tooltip :content="termTooltip" :disabled="canManageTerm" placement="top">
              <span>
                <el-button size="small" text type="primary" :disabled="!canManageTerm" @click="openEdit(row)">
                  编辑
                </el-button>
                <el-button size="small" text type="danger" :disabled="!canManageTerm" @click="handleDelete(row)">
                  删除
                </el-button>
              </span>
            </el-tooltip>
          </template>
        </el-table-column>
      </el-table>

      <div class="pagination">
        <el-pagination
          layout="total, prev, pager, next"
          :total="total"
          :current-page="page"
          :page-size="pageSize"
          @current-change="handlePageChange"
        />
      </div>
    </el-card>

    <!-- 检索预览 -->
    <el-card shadow="hover" class="search-card">
      <template #header>
        <span>检索预览（验证 RAG 召回内容）</span>
      </template>

      <el-form :inline="true" class="search-form">
        <el-form-item label="查询">
          <el-input
            v-model="searchQuery"
            placeholder="输入检索内容"
            style="width: 280px"
            clearable
            @keyup.enter="handleRagSearch"
          />
        </el-form-item>
        <el-form-item label="知识库">
          <el-select v-model="searchKbType" style="width: 140px">
            <el-option v-for="opt in kbTypeOptions" :key="opt.value" :label="opt.label" :value="opt.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="Top-K">
          <el-input-number v-model="searchTopK" :min="1" :max="20" :step="1" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="searchLoading" @click="handleRagSearch">检索</el-button>
        </el-form-item>
      </el-form>

      <el-empty v-if="!searchChunks.length && !searchLoading" description="暂无检索结果" />
      <el-alert
        v-else-if="searchChunks.length"
        type="success"
        :closable="false"
        :title="`共召回 ${searchChunks.length} 条内容（按相似度降序）`"
        style="margin-bottom: 12px"
      />
      <div v-for="(chunk, idx) in searchChunks" :key="idx" class="chunk-result">
        <div class="chunk-meta">
          <el-tag size="small" type="primary" effect="plain">#{{ idx + 1 }}</el-tag>
          <el-tag size="small" effect="plain">
            {{ kbTypeLabel(chunk.kb_type) }}
          </el-tag>
          <span class="chunk-score">score: {{ chunk.score.toFixed(3) }}</span>
        </div>
        <pre class="chunk-content">{{ chunk.content }}</pre>
      </div>
    </el-card>

    <!-- 术语编辑/新建弹窗 -->
    <el-dialog
      v-model="dialogVisible"
      :title="dialogMode === 'create' ? '新建术语' : '编辑术语'"
      width="560px"
      @closed="resetForm"
    >
      <el-form label-width="90px">
        <el-form-item label="术语" required>
          <el-input v-model="termForm.term" placeholder="必填，如：幂等性" />
        </el-form-item>
        <el-form-item label="技术含义" required>
          <el-input
            v-model="termForm.technical_meaning"
            type="textarea"
            :rows="3"
            placeholder="必填，描述该术语的技术含义"
          />
        </el-form-item>
        <el-form-item label="别名">
          <el-select
            v-model="termForm.aliases"
            multiple
            filterable
            allow-create
            default-first-option
            placeholder="可输入别名后回车添加（多标签）"
            style="width: 100%"
          >
            <el-option v-for="a in termForm.aliases" :key="a" :label="a" :value="a" />
          </el-select>
        </el-form-item>
        <el-form-item label="领域">
          <el-input v-model="termForm.domain" placeholder="可选，如：接口测试" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submitTerm">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { knowledgeApi, KbType } from '@/api'
import { useAuthStore } from '@/stores'

// ============ 权限控制 ============
// 当前用户角色（响应式，取自 pinia auth store，与 Layout.vue 同一套来源）
const authStore = useAuthStore()
// 当前用户角色（响应式，取自 pinia auth store，与 Layout.vue 同一套来源）
const role = computed<string>(() => authStore.role)
const canRebuild = computed<boolean>(() => ['super_admin', 'admin'].includes(role.value))
const canManageTerm = computed<boolean>(() =>
  ['super_admin', 'admin', 'test_manager'].includes(role.value)
)
const termTooltip = '仅超级管理员 / 系统管理员 / 测试经理可维护术语'

// ============ 类型定义 ============
interface KbStatus {
  enabled: boolean
  chunk_counts: { defect: number; case: number; doc: number; term: number }
  chunk_count: number
  term_count: number
  embedding_model_id: string | null
  state: 'idle' | 'running'
  last_rebuild: string | null
}

interface TermItem {
  id: string
  term: string
  aliases: string[]
  technical_meaning: string
  domain: string
  created_at: string | null
  updated_at: string | null
}

interface SearchChunk {
  content: string
  kb_type: string
  score: number
}

interface TermForm {
  id: string | null
  term: string
  technical_meaning: string
  aliases: string[]
  domain: string
}

// ============ 状态数据 ============
const status = ref<KbStatus>({
  enabled: false,
  chunk_counts: { defect: 0, case: 0, doc: 0, term: 0 },
  chunk_count: 0,
  term_count: 0,
  embedding_model_id: null,
  state: 'idle',
  last_rebuild: null,
})

const chunkCountList = computed<Array<{ key: string; label: string; count: number }>>(() => [
  { key: 'defect', label: '缺陷', count: status.value.chunk_counts.defect },
  { key: 'case', label: '用例', count: status.value.chunk_counts.case },
  { key: 'doc', label: '接口文档', count: status.value.chunk_counts.doc },
  { key: 'term', label: '术语', count: status.value.chunk_counts.term },
])

// ============ 术语表 ============
const terms = ref<TermItem[]>([])
const total = ref<number>(0)
const page = ref<number>(1)
const pageSize = ref<number>(20)
const searchKeyword = ref<string>('')
const termsLoading = ref<boolean>(false)

// ============ 重建 ============
const rebuildType = ref<KbType | ''>('')
const rebuildLoading = ref<boolean>(false)
const rebuildDisabled = computed<boolean>(
  () => !canRebuild.value || status.value.state === 'running'
)
const rebuildTooltip = computed<string>(() => {
  if (!canRebuild.value) return '仅超级管理员 / 系统管理员可执行一键重建'
  if (status.value.state === 'running') return '知识库正在重建中，请稍候'
  return ''
})

// ============ 检索预览 ============
const searchQuery = ref<string>('')
const searchKbType = ref<string>('all')
const searchTopK = ref<number>(5)
const searchLoading = ref<boolean>(false)
const searchChunks = ref<SearchChunk[]>([])
const kbTypeOptions = [
  { value: 'all', label: '全部' },
  { value: 'defect', label: '缺陷' },
  { value: 'case', label: '用例' },
  { value: 'doc', label: '接口文档' },
  { value: 'term', label: '术语' },
]

// ============ 弹窗表单 ============
const dialogVisible = ref<boolean>(false)
const dialogMode = ref<'create' | 'edit'>('create')
const submitting = ref<boolean>(false)
const termForm = reactive<TermForm>({
  id: null,
  term: '',
  technical_meaning: '',
  aliases: [],
  domain: '',
})

// ============ 工具函数 ============
function formatTime(value: string | null): string {
  if (!value) return '尚未重建'
  const d = new Date(value)
  if (isNaN(d.getTime())) return value
  return d.toLocaleString('zh-CN', { hour12: false })
}

function kbTypeLabel(value: string): string {
  const hit = kbTypeOptions.find((o) => o.value === value)
  return hit ? hit.label : value
}

// ============ 状态加载 ============
async function loadStatus(): Promise<void> {
  try {
    const res: any = await knowledgeApi.getStatus()
    if (res?.code === 0 && res?.data) {
      const d = res.data
      status.value = {
        enabled: !!d.enabled,
        chunk_counts: {
          defect: d.chunk_counts?.defect ?? 0,
          case: d.chunk_counts?.case ?? 0,
          doc: d.chunk_counts?.doc ?? 0,
          term: d.chunk_counts?.term ?? 0,
        },
        chunk_count: d.chunk_count ?? 0,
        term_count: d.term_count ?? 0,
        embedding_model_id: d.embedding_model_id ?? null,
        state: d.state === 'running' ? 'running' : 'idle',
        last_rebuild: d.last_rebuild ?? null,
      }
    }
  } catch {
    /* 网络异常，保持默认状态 */
  }
}

// ============ 术语列表 ============
async function loadTerms(): Promise<void> {
  try {
    termsLoading.value = true
    const res: any = await knowledgeApi.listTerms({
      page: page.value,
      size: pageSize.value,
      q: searchKeyword.value,
    })
    terms.value = res?.data?.list ?? []
    total.value = res?.data?.total ?? 0
  } catch {
    terms.value = []
    total.value = 0
  } finally {
    termsLoading.value = false
  }
}

function handleTermSearch(): void {
  page.value = 1
  void loadTerms()
}

function handlePageChange(p: number): void {
  page.value = p
  void loadTerms()
}

// ============ 重建 ============
async function handleRebuild(): Promise<void> {
  try {
    rebuildLoading.value = true
    const payload: KbType | undefined = rebuildType.value === '' ? undefined : rebuildType.value
    const res: any = await knowledgeApi.rebuild(payload)
    if (res?.code === 0) {
      const taskId = res?.data?.task_id
      ElMessage.success(`重建任务已提交（task_id: ${taskId}），请稍后刷新查看进度`)
      void loadStatus()
    } else if (res?.code === 1) {
      // 后端返回 code:1（如「重建任务进行中，请勿重复提交」）—— 作为警告提示，不当异常抛
      ElMessage.warning(res?.message || '重建任务进行中，请勿重复提交')
    } else {
      ElMessage.error(res?.message || '重建失败')
    }
  } catch {
    /* 拦截器已处理网络异常 */
  } finally {
    rebuildLoading.value = false
  }
}

// ============ 术语新建 / 编辑 ============
function openCreate(): void {
  dialogMode.value = 'create'
  resetForm()
  dialogVisible.value = true
}

async function openEdit(row: TermItem): Promise<void> {
  dialogMode.value = 'edit'
  termForm.id = row.id
  termForm.term = row.term
  termForm.technical_meaning = row.technical_meaning
  termForm.aliases = Array.isArray(row.aliases) ? [...row.aliases] : []
  termForm.domain = row.domain || ''
  dialogVisible.value = true
}

function resetForm(): void {
  termForm.id = null
  termForm.term = ''
  termForm.technical_meaning = ''
  termForm.aliases = []
  termForm.domain = ''
}

async function submitTerm(): Promise<void> {
  if (!termForm.term.trim()) {
    ElMessage.warning('术语名称必填')
    return
  }
  if (!termForm.technical_meaning.trim()) {
    ElMessage.warning('技术含义必填')
    return
  }
  try {
    submitting.value = true
    const payload = {
      term: termForm.term.trim(),
      technical_meaning: termForm.technical_meaning.trim(),
      aliases: termForm.aliases,
      domain: termForm.domain.trim() || undefined,
    }
    if (dialogMode.value === 'create') {
      const res: any = await knowledgeApi.createTerm(payload)
      if (res?.code === 0) {
        ElMessage.success('术语已创建')
      } else if (res?.code === 1) {
        // 「术语已存在」等，提示而非抛异常
        ElMessage.warning(res?.message || '术语已存在')
        return
      } else {
        ElMessage.error(res?.message || '创建失败')
        return
      }
    } else {
      const res: any = await knowledgeApi.updateTerm(termForm.id as string, payload)
      if (res?.code === 0) {
        ElMessage.success('术语已更新')
      } else if (res?.code === 1) {
        ElMessage.warning(res?.message || '术语已存在')
        return
      } else {
        ElMessage.error(res?.message || '更新失败')
        return
      }
    }
    dialogVisible.value = false
    await Promise.all([loadTerms(), loadStatus()])
  } catch {
    /* 拦截器已处理网络异常 */
  } finally {
    submitting.value = false
  }
}

// ============ 术语删除 ============
async function handleDelete(row: TermItem): Promise<void> {
  try {
    await ElMessageBox.confirm(`确定删除术语「${row.term}」吗？此操作不可恢复。`, '删除确认', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  try {
    const res: any = await knowledgeApi.removeTerm(row.id)
    if (res?.code === 0) {
      ElMessage.success('已删除')
      await Promise.all([loadTerms(), loadStatus()])
    } else {
      ElMessage.error(res?.message || '删除失败')
    }
  } catch {
    /* 拦截器已处理网络异常 */
  }
}

// ============ 检索预览 ============
async function handleRagSearch(): Promise<void> {
  if (!searchQuery.value.trim()) {
    ElMessage.warning('请输入检索内容')
    return
  }
  try {
    searchLoading.value = true
    const res: any = await knowledgeApi.search({
      query: searchQuery.value.trim(),
      kb_type: searchKbType.value,
      top_k: searchTopK.value,
    })
    const list: SearchChunk[] = res?.data?.chunks ?? []
    // 按相似度（score）降序，score 保留 3 位小数（展示层 toFixed）
    searchChunks.value = [...list].sort((a: SearchChunk, b: SearchChunk) => b.score - a.score)
  } catch {
    searchChunks.value = []
  } finally {
    searchLoading.value = false
  }
}

// ============ 初始化 ============
onMounted(() => {
  void loadStatus()
  void loadTerms()
})
</script>

<style scoped>
.knowledge-base {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}
.stat-item {
  margin-bottom: 8px;
}
.stat-label {
  font-size: 13px;
  color: #909399;
  margin-bottom: 6px;
}
.stat-value {
  font-size: 20px;
  font-weight: 600;
  color: #303133;
}
.stat-value-sm {
  font-size: 14px;
  color: #303133;
}
.text-ellipsis {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.chunk-box {
  background: #f5f7fa;
  border-radius: 6px;
  padding: 14px;
  text-align: center;
  margin-bottom: 8px;
}
.chunk-count {
  font-size: 22px;
  font-weight: 700;
  color: #409eff;
}
.chunk-label {
  font-size: 13px;
  color: #909399;
  margin-top: 4px;
}
.pagination {
  margin-top: 12px;
  display: flex;
  justify-content: flex-end;
}
.muted {
  color: #c0c4cc;
}
.search-form {
  margin-bottom: 8px;
}
.chunk-result {
  border: 1px solid #ebeef5;
  border-radius: 6px;
  padding: 10px 12px;
  margin-bottom: 10px;
  background: #fafafa;
}
.chunk-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}
.chunk-score {
  font-size: 12px;
  color: #909399;
}
.chunk-content {
  font-family: Consolas, Monaco, monospace;
  font-size: 13px;
  white-space: pre-wrap;
  word-break: break-all;
  margin: 0;
  color: #303133;
  max-height: 320px;
  overflow: auto;
}
</style>
