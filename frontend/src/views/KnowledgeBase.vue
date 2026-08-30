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
            <el-checkbox
              v-model="forceFull"
              title="清空该知识库全部切片后全量重建（默认增量）"
            >
              强制全量重建
            </el-checkbox>
            <el-button :disabled="rebuildLoading" @click="loadStatus">刷新</el-button>
          </div>
        </div>
      </template>

      <el-alert
        v-if="!status.enabled"
        type="warning"
        :closable="false"
        show-icon
        title="知识库检索未启用"
        description="请在下方「RAG 开关」中开启，或联系系统管理员。"
        style="margin-bottom: 16px"
      />

      <el-row :gutter="16">
        <el-col :xs="12" :sm="8" :md="6">
          <div class="stat-item">
            <div class="stat-label">RAG 开关</div>
            <div class="stat-value">
              <el-switch
                v-model="kbEnabled"
                :loading="kbEnabledLoading"
                :disabled="!canToggleKb"
                @change="onKbEnabledChange"
              />
              <el-tag
                :type="status.enabled ? 'success' : 'info'"
                effect="plain"
                size="small"
                style="margin-left: 8px"
              >
                {{ status.enabled ? '已启用' : '未启用' }}
              </el-tag>
              <el-tooltip
                v-if="!canToggleKb"
                content="仅超级管理员 / 系统管理员可切换"
                placement="top"
              >
                <el-icon style="margin-left: 4px; color: #909399"><QuestionFilled /></el-icon>
              </el-tooltip>
            </div>
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
            <div class="stat-label">检索模式</div>
            <div class="stat-value">
              <el-tag :type="status.retrieval_mode === 'semantic' ? 'success' : 'info'" effect="plain">
                {{ status.retrieval_mode === 'semantic' ? '语义检索' : '关键词模式' }}
              </el-tag>
              <span v-if="status.embedding_ready" class="ready-badge">✓ 语义就绪</span>
            </div>
          </div>
        </el-col>
        <el-col :xs="12" :sm="8" :md="6">
          <div class="stat-item">
            <div class="stat-label">重建状态</div>
            <div>
              <el-tag :type="stateTagType" effect="plain">
                {{ stateLabel }}
              </el-tag>
              <el-tooltip
                v-if="status.is_stuck"
                content="重建任务超过 1 小时无响应，可能 celery-worker 容器异常。点击「强制重置」恢复。"
                placement="top"
              >
                <el-icon style="margin-left: 4px; color: #f56c6c"><WarningFilled /></el-icon>
              </el-tooltip>
              <el-button
                v-if="status.is_stuck && canRebuild"
                type="danger"
                size="small"
                style="margin-left: 8px"
                :loading="resetLoading"
                @click="handleForceReset"
              >
                强制重置
              </el-button>
            </div>
            <div v-if="status.state === 'failed' && status.error" class="state-error">
              <el-text type="danger" size="small">上次失败：{{ status.error }}</el-text>
            </div>
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

    <!-- 知识文档（P0 文档中心化） -->
    <el-card shadow="hover" class="doc-card">
      <template #header>
        <div class="card-header">
          <span>知识文档（上传测试规范 / 经验手册，AI 回答将引用此处内容）</span>
          <div class="header-actions">
            <el-select
              v-model="docsProjectFilter"
              placeholder="按项目过滤"
              clearable
              style="width: 180px"
              @change="handleDocsFilterChange"
            >
              <el-option v-for="p in projects" :key="p.id" :label="p.name" :value="p.id" />
            </el-select>
            <el-select
              v-model="docsStatusFilter"
              placeholder="状态"
              clearable
              style="width: 120px"
              @change="handleDocsFilterChange"
            >
              <el-option label="解析索引中" value="parsing" />
              <el-option label="已索引" value="indexed" />
              <el-option label="失败" value="failed" />
            </el-select>
            <el-tooltip
              content="viewer / auditor 无上传权限"
              :disabled="canWriteDoc"
              placement="top"
            >
              <span>
                <el-button type="primary" :disabled="!canWriteDoc" @click="openUpload">
                  上传知识文档
                </el-button>
              </span>
            </el-tooltip>
            <el-button :disabled="docsLoading" @click="loadDocs">刷新</el-button>
          </div>
        </div>
      </template>

      <el-table
        :data="docs"
        v-loading="docsLoading"
        size="small"
        border
        empty-text="暂无知识文档，点击右上角「上传知识文档」开始"
        style="width: 100%"
      >
        <el-table-column prop="title" label="标题" min-width="200" show-overflow-tooltip />
        <el-table-column prop="category" label="分类" width="110">
          <template #default="{ row }">
            {{ row.category || '—' }}
          </template>
        </el-table-column>
        <el-table-column prop="file_type" label="类型" width="80" />
        <el-table-column label="大小" width="100">
          <template #default="{ row }">{{ formatFileSize(row.file_size) }}</template>
        </el-table-column>
        <el-table-column label="状态" width="120">
          <template #default="{ row }">
            <el-tooltip
              v-if="row.status === 'failed' && row.error"
              :content="row.error"
              placement="top"
            >
              <el-tag :type="DOC_STATUS_MAP[row.status]?.type || 'info'" size="small">
                {{ DOC_STATUS_MAP[row.status]?.label || row.status }}
              </el-tag>
            </el-tooltip>
            <el-tag v-else :type="DOC_STATUS_MAP[row.status]?.type || 'info'" size="small">
              {{ DOC_STATUS_MAP[row.status]?.label || row.status }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="chunk_count" label="切片数" width="80" />
        <el-table-column label="上传时间" width="170">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="160" fixed="right">
          <template #default="{ row }">
            <el-tooltip content="更换嵌入模型后可重新索引" placement="top">
              <el-button
                size="small"
                text
                type="primary"
                :disabled="!canWriteDoc || row.status === 'parsing'"
                @click="handleReindex(row)"
              >
                重新索引
              </el-button>
            </el-tooltip>
            <el-tooltip :content="termTooltip" :disabled="canDeleteDoc" placement="top">
              <span>
                <el-button
                  size="small"
                  text
                  type="danger"
                  :disabled="!canDeleteDoc"
                  @click="handleDocDelete(row)"
                >
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
          :total="docsTotal"
          :current-page="docsPage"
          :page-size="docsPageSize"
          @current-change="handleDocsPageChange"
        />
      </div>
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
          <span v-if="chunk.source" class="chunk-source">来源：{{ chunk.source }}</span>
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

    <!-- 知识文档上传弹窗 -->
    <el-dialog v-model="uploadVisible" title="上传知识文档" width="560px">
      <el-form label-width="90px">
        <el-form-item label="文档文件" required>
          <el-upload
            drag
            :auto-upload="false"
            :limit="1"
            accept=".pdf,.docx,.md,.txt"
            :on-change="onUploadFileChange"
            :on-remove="() => (uploadFileRef = null)"
            style="width: 100%"
          >
            <el-icon style="font-size: 32px; color: #c0c4cc"><UploadFilled /></el-icon>
            <div class="el-upload__text">拖拽文件到此处，或<em>点击选择</em></div>
            <template #tip>
              <div class="el-upload__tip">支持 pdf / docx / md / txt，≤ 20MB</div>
            </template>
          </el-upload>
        </el-form-item>
        <el-form-item label="所属项目" required>
          <el-select v-model="uploadForm.project_id" placeholder="选择项目" style="width: 100%">
            <el-option v-for="p in projects" :key="p.id" :label="p.name" :value="p.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="标题">
          <el-input v-model="uploadForm.title" placeholder="默认取文件名" />
        </el-form-item>
        <el-form-item label="分类">
          <el-select
            v-model="uploadForm.category"
            placeholder="选择或输入分类"
            filterable
            allow-create
            default-first-option
            clearable
            style="width: 100%"
          >
            <el-option v-for="c in DOC_CATEGORY_OPTIONS" :key="c" :label="c" :value="c" />
          </el-select>
        </el-form-item>
        <el-form-item label="描述">
          <el-input
            v-model="uploadForm.description"
            type="textarea"
            :rows="2"
            placeholder="可选，文档用途说明"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="uploadVisible = false">取消</el-button>
        <el-button type="primary" :loading="uploading" @click="submitUpload">
          上传并索引
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted, onUnmounted, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { knowledgeApi, projectApi, KbType } from '@/api'
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
  chunk_counts: { defect: number; case: number; doc: number; term: number; document: number }
  chunk_count: number
  term_count: number
  embedding_model_id: string | null
  embedding_ready: boolean
  retrieval_mode: string
  state: 'idle' | 'running' | 'failed'
  last_rebuild: string | null
  is_stuck: boolean
  error?: string | null
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
  source?: string
}

interface KnowledgeDocItem {
  id: string
  project_id: string
  title: string
  filename: string
  file_type: string
  category: string | null
  status: 'parsing' | 'indexed' | 'failed'
  chunk_count: number
  error: string | null
  file_size: number
  created_at: string | null
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
  chunk_counts: { defect: 0, case: 0, doc: 0, term: 0, document: 0 },
  chunk_count: 0,
  term_count: 0,
  embedding_model_id: null,
  embedding_ready: false,
  retrieval_mode: 'keyword',
  state: 'idle',
  last_rebuild: null,
  is_stuck: false,
})

// 知识库总开关 toggle（admin 可切；切换即生效，无需重启）
const kbEnabled = ref<boolean>(false)
const kbEnabledLoading = ref<boolean>(false)
const canToggleKb = computed<boolean>(
  () => ['super_admin', 'admin'].includes(role.value)
)

const chunkCountList = computed<Array<{ key: string; label: string; count: number }>>(() => [
  { key: 'document', label: '知识文档', count: status.value.chunk_counts.document },
  { key: 'defect', label: '缺陷', count: status.value.chunk_counts.defect },
  { key: 'case', label: '用例', count: status.value.chunk_counts.case },
  { key: 'doc', label: '接口资产', count: status.value.chunk_counts.doc },
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
// 强制全量重建开关（默认增量；仅作 UI 开关，权限由「一键重建」按钮包裹）
const forceFull = ref<boolean>(false)
const rebuildType = ref<KbType | ''>('')
const rebuildLoading = ref<boolean>(false)
const resetLoading = ref<boolean>(false)
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
  { value: 'document', label: '知识文档' },
  { value: 'defect', label: '缺陷' },
  { value: 'case', label: '用例' },
  { value: 'doc', label: '接口资产' },
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

// ============ 状态展示计算属性 ============
// 区分 running / idle / failed 三态：失败时显式提示 + 红色 tag
const stateTagType = computed<'success' | 'warning' | 'danger'>(() => {
  if (status.value.state === 'running') {
    return status.value.is_stuck ? 'danger' : 'warning'
  }
  if (status.value.state === 'failed') {
    return 'danger'
  }
  return 'success'
})

const stateLabel = computed<string>(() => {
  if (status.value.state === 'running') {
    return status.value.is_stuck ? '⚠ 卡死' : '重建中…'
  }
  if (status.value.state === 'failed') {
    return '失败'
  }
  return '空闲'
})

// ============ 状态加载 ============
// 上一帧状态（用于检测 running→idle/failed 的边沿变化，弹提示）
const prevState = ref<'idle' | 'running' | 'failed'>('idle')

// 状态轮询：state==running 时每 5s 拉一次，后端 idle/failed 时停止
let pollTimer: ReturnType<typeof setInterval> | null = null
const STATUS_POLL_INTERVAL = 5000

function startStatusPolling(): void {
  if (pollTimer) return
  pollTimer = setInterval(() => {
    void loadStatus()
  }, STATUS_POLL_INTERVAL)
}

function stopStatusPolling(): void {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

watch(
  () => status.value.state,
  (newState) => {
    if (newState === 'running') startStatusPolling()
    else stopStatusPolling()
  },
  { immediate: true }
)

onUnmounted(() => {
  stopStatusPolling()
})

async function loadStatus(): Promise<void> {
  try {
    const res: any = await knowledgeApi.getStatus()
    if (res?.code === 0 && res?.data) {
      const d = res.data
      const newState: 'idle' | 'running' | 'failed' =
        d.state === 'running' ? 'running' :
        d.state === 'failed' ? 'failed' : 'idle'
      const newChunkCount = d.chunk_count ?? 0

      // 边沿检测：running→idle 时弹"重建完成"提示（用户体验核心改进）
      if (prevState.value === 'running' && newState === 'idle') {
        ElMessage.success(
          `重建完成，共 ${newChunkCount} 个切片`
        )
      }
      // 边沿检测：running→failed 时弹"重建失败"提示（用户能立即看到异常）
      if (prevState.value === 'running' && newState === 'failed') {
        ElMessage.error(`重建失败：${d.error || '未知错误'}`)
      }
      prevState.value = newState

      status.value = {
        enabled: !!d.enabled,
        chunk_counts: {
          defect: d.chunk_counts?.defect ?? 0,
          case: d.chunk_counts?.case ?? 0,
          doc: d.chunk_counts?.doc ?? 0,
          term: d.chunk_counts?.term ?? 0,
          document: d.chunk_counts?.document ?? 0,
        },
        chunk_count: newChunkCount,
        term_count: d.term_count ?? 0,
        embedding_model_id: d.embedding_model_id ?? null,
        embedding_ready: d.embedding_ready ?? false,
        retrieval_mode: d.retrieval_mode ?? 'keyword',
        state: newState,
        last_rebuild: d.last_rebuild ?? null,
        is_stuck: !!d.is_stuck,
        error: d.error ?? null,
      }
      // 同步 toggle 状态；与后端状态一致
      kbEnabled.value = !!d.enabled
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
    const res: any = await knowledgeApi.rebuild(payload, forceFull.value)
    if (res?.code === 0) {
      const taskId = res?.data?.task_id
      const stuckReset = res?.data?.stuck_reset
      const msg = stuckReset
        ? `上次任务疑似卡死已自动重置，新任务已提交（task_id: ${taskId}）。请检查 celery-worker 容器。`
        : `重建任务已提交（task_id: ${taskId}），请稍后刷新查看进度`
      ElMessage.success(msg)
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

// 强制重置状态机（admin）：用于卡死时人工干预
async function handleForceReset(): Promise<void> {
  try {
    await ElMessageBox.confirm(
      '确认强制重置重建状态？这会清掉当前卡死任务并把状态推回 idle，但不会终止 Celery 中可能仍在跑的任务。',
      '强制重置',
      { type: 'warning', confirmButtonText: '确认重置', cancelButtonText: '取消' }
    )
  } catch {
    return
  }
  try {
    resetLoading.value = true
    const res: any = await knowledgeApi.reset()
    if (res?.code === 0) {
      ElMessage.success('重建状态已重置')
      void loadStatus()
    } else {
      ElMessage.error(res?.message || '重置失败')
    }
  } catch {
    /* 拦截器已处理网络异常 */
  } finally {
    resetLoading.value = false
  }
}

// 运行时切换 KB_RAG_ENABLED（admin）。后端写入 kb_runtime_config 表 + 即时失效缓存。
async function onKbEnabledChange(value: boolean): Promise<void> {
  if (!canToggleKb.value) {
    kbEnabled.value = status.value.enabled
    return
  }
  try {
    kbEnabledLoading.value = true
    const res: any = await knowledgeApi.updateConfig({ kb_rag_enabled: value })
    if (res?.code === 0) {
      status.value.enabled = value
      ElMessage.success(value ? '已启用知识库检索' : '已停用知识库检索')
    } else {
      // 失败回滚 UI
      kbEnabled.value = status.value.enabled
      ElMessage.error(res?.message || '切换失败')
    }
  } catch {
    kbEnabled.value = status.value.enabled
  } finally {
    kbEnabledLoading.value = false
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
      project_id: docsProjectFilter.value || undefined,
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

// ============ 知识文档（P0 文档中心化） ============
const projects = ref<Array<{ id: string; name: string }>>([])
const docs = ref<KnowledgeDocItem[]>([])
const docsTotal = ref<number>(0)
const docsPage = ref<number>(1)
const docsPageSize = ref<number>(10)
const docsLoading = ref<boolean>(false)
const docsProjectFilter = ref<string>('')
const docsStatusFilter = ref<string>('')
// viewer / auditor 只读；其余可上传
const canWriteDoc = computed<boolean>(
  () => !['viewer', 'auditor'].includes(role.value)
)
const canDeleteDoc = computed<boolean>(() => canManageTerm.value)

const uploadVisible = ref<boolean>(false)
const uploading = ref<boolean>(false)
const uploadForm = reactive({
  project_id: '',
  title: '',
  category: '',
  description: '',
})
const uploadFileRef = ref<File | null>(null)

const DOC_STATUS_MAP: Record<string, { label: string; type: 'success' | 'warning' | 'danger' | 'info' }> = {
  parsing: { label: '解析索引中', type: 'warning' },
  indexed: { label: '已索引', type: 'success' },
  failed: { label: '失败', type: 'danger' },
}

const DOC_CATEGORY_OPTIONS = ['测试规范', '技术知识', '测试经验', 'FAQ', '项目文档']

function formatFileSize(size: number): string {
  if (!size) return '—'
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / 1024 / 1024).toFixed(1)} MB`
}

async function loadProjects(): Promise<void> {
  try {
    const res: any = await projectApi.getList()
    projects.value = res?.data ?? []
  } catch {
    projects.value = []
  }
}

async function loadDocs(): Promise<void> {
  try {
    docsLoading.value = true
    const res: any = await knowledgeApi.listDocuments({
      page: docsPage.value,
      size: docsPageSize.value,
      project_id: docsProjectFilter.value || undefined,
      status: docsStatusFilter.value || undefined,
    })
    docs.value = res?.data?.list ?? []
    docsTotal.value = res?.data?.total ?? 0
  } catch {
    docs.value = []
    docsTotal.value = 0
  } finally {
    docsLoading.value = false
  }
}

function handleDocsFilterChange(): void {
  docsPage.value = 1
  void loadDocs()
}

function handleDocsPageChange(p: number): void {
  docsPage.value = p
  void loadDocs()
}

function openUpload(): void {
  uploadForm.project_id = docsProjectFilter.value || ''
  uploadForm.title = ''
  uploadForm.category = ''
  uploadForm.description = ''
  uploadFileRef.value = null
  uploadVisible.value = true
}

function onUploadFileChange(file: any): void {
  uploadFileRef.value = file?.raw ?? null
}

async function submitUpload(): Promise<void> {
  if (!uploadFileRef.value) {
    ElMessage.warning('请选择文件（pdf / docx / md / txt）')
    return
  }
  if (!uploadForm.project_id) {
    ElMessage.warning('请选择所属项目')
    return
  }
  try {
    uploading.value = true
    const res: any = await knowledgeApi.uploadDocument(uploadFileRef.value, {
      project_id: uploadForm.project_id,
      title: uploadForm.title.trim() || undefined,
      category: uploadForm.category || undefined,
      description: uploadForm.description.trim() || undefined,
    })
    if (res?.code === 0) {
      ElMessage.success('上传成功，正在解析索引')
      uploadVisible.value = false
      docsProjectFilter.value = uploadForm.project_id
      docsPage.value = 1
      await Promise.all([loadDocs(), loadStatus()])
    } else {
      ElMessage.error(res?.message || '上传失败')
    }
  } catch {
    /* 拦截器已处理网络异常 */
  } finally {
    uploading.value = false
  }
}

async function handleDocDelete(row: KnowledgeDocItem): Promise<void> {
  try {
    await ElMessageBox.confirm(
      `确定删除文档「${row.title}」吗？将同时删除其全部知识切片，此操作不可恢复。`,
      '删除确认',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }
    )
  } catch {
    return
  }
  try {
    const res: any = await knowledgeApi.removeDocument(row.id)
    if (res?.code === 0) {
      ElMessage.success('已删除（含全部切片）')
      await Promise.all([loadDocs(), loadStatus()])
    } else {
      ElMessage.error(res?.message || '删除失败')
    }
  } catch {
    /* 拦截器已处理网络异常 */
  }
}

async function handleReindex(row: KnowledgeDocItem): Promise<void> {
  try {
    const res: any = await knowledgeApi.reindexDocument(row.id)
    if (res?.code === 0) {
      ElMessage.success('已派发重新索引任务')
      await Promise.all([loadDocs(), loadStatus()])
    } else {
      ElMessage.error(res?.message || '重新索引失败')
    }
  } catch {
    /* 拦截器已处理网络异常 */
  }
}

// ============ 初始化 ============
onMounted(() => {
  void loadStatus()
  void loadTerms()
  void loadProjects()
  void loadDocs()
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
.ready-badge {
  margin-left: 8px;
  font-size: 12px;
  font-weight: 600;
  color: #67c23a;
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
.chunk-source {
  font-size: 12px;
  color: #67c23a;
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
