<template>
  <div class="doc-parser">
    <el-row :gutter="16">
      <!-- 左：上传 + 解析 -->
      <el-col :xs="24" :lg="14">
        <el-alert
          v-if="restoringDoc"
          type="info"
          :closable="false"
          show-icon
          title="正在恢复上次解析的接口文档…"
          style="margin-bottom: 12px"
        />
        <el-alert
          v-if="parseFeedback"
          :type="parseFeedback.type"
          :closable="true"
          show-icon
          :title="parseFeedback.title"
          :description="parseFeedback.description"
          style="margin-bottom: 12px"
          @close="parseFeedback = null"
        />
        <el-card shadow="hover">
          <template #header>1. 选择项目并上传接口文档</template>

          <el-form label-width="100px">
            <el-form-item label="项目" required>
              <el-select v-model="projectId" placeholder="选择项目" filterable style="width: 100%" @change="onProjectChange">
                <el-option v-for="p in projects" :key="p.id" :label="p.name" :value="p.id" />
              </el-select>
            </el-form-item>
            <el-form-item label="文档类型">
              <el-select v-model="docType" placeholder="自动探测" clearable style="width: 100%">
                <el-option label="自动探测" value="" />
                <el-option label="OpenAPI / Swagger" value="openapi" />
                <el-option label="HAR" value="har" />
                <el-option label="Word (docx)" value="docx" />
                <el-option label="PDF" value="pdf" />
                <el-option label="纯文本 (txt)" value="txt" />
              </el-select>
            </el-form-item>
          </el-form>

          <el-upload
            drag
            :auto-upload="false"
            :limit="1"
            :show-file-list="true"
            accept=".json,.yaml,.yml,.har,.docx,.pdf,.txt"
            :on-change="onFileChange"
            :on-exceed="() => ElMessage.warning('每次仅可上传一个文件')"
          >
            <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
            <div class="el-upload__text">拖入文件或 <em>点击选择</em></div>
            <template #tip>
              <div class="el-upload__tip">
                支持 openapi / har / docx / pdf / txt，单文件 ≤ 20MB。
                OpenAPI / HAR 为规则解析（精准）；docx / pdf 依赖 AI（结果需人工复核）。
              </div>
            </template>
          </el-upload>

          <div class="actions">
            <el-button
              type="primary"
              :loading="uploading"
              :disabled="!projectId || !selectedFile"
              @click="uploadAndParse"
            >
              上传并解析
            </el-button>
            <el-button :disabled="!selectedFile" @click="clearFile">清除</el-button>
          </div>

          <el-steps :active="activeStep" align-center class="steps">
            <el-step title="上传文件" />
            <el-step title="AI 解析" />
            <el-step title="预览确认" />
            <el-step title="导入资产" />
          </el-steps>
        </el-card>

        <el-card shadow="hover" v-if="currentDoc" v-loading="reparsingDocId === currentDoc.doc_id" style="margin-top: 16px">
          <template #header>
            2. 解析结果
            <el-tag size="small" style="margin-left: 8px">{{ currentDoc.parse_engine }}</el-tag>
            <el-tag size="small" type="info" style="margin-left: 8px">
              共 {{ endpoints.length }} 个接口
            </el-tag>
          </template>

          <el-alert
            v-if="currentDoc.degraded"
            type="warning"
            :closable="false"
            show-icon
            title="未配置 AI 模型或 AI 解析失败，仅提取到接口骨架（method + path）"
            description="请在「系统配置 / AI 模型配置」中配置文档解析模型后重新解析，以获得完整参数与响应定义。"
            style="margin-bottom: 12px"
          />
          <el-alert
            v-if="currentDoc.scanned"
            type="error"
            :closable="false"
            show-icon
            title="疑似扫描版 PDF，无可提取文本"
            description="本版本不支持 OCR，请提供可复制文本的 PDF 或 Word 文档。"
            style="margin-bottom: 12px"
          />

          <div v-if="unparsedNotes.length" class="notes">
            <el-collapse>
              <el-collapse-item title="解析备注 / 未覆盖内容" name="1">
                <ul>
                  <li v-for="(n, i) in unparsedNotes" :key="i">{{ n }}</li>
                </ul>
              </el-collapse-item>
            </el-collapse>
          </div>

          <ApiSpecTable
            :endpoints="endpoints"
            selectable
            :loading="uploading"
            show-confidence
            v-model="selectedKeys"
          />

          <div class="import-bar">
            <span>已选 {{ selectedKeys.length }} / {{ endpoints.length }}</span>
            <div>
              <el-checkbox v-model="overwrite" style="margin-right: 12px">覆盖同名接口</el-checkbox>
              <el-button
                type="primary"
                :disabled="selectedKeys.length === 0"
                @click="importSelected"
              >
                导入选中 ({{ selectedKeys.length }})
              </el-button>
              <el-button :disabled="endpoints.length === 0" @click="importAll">导入全部</el-button>
              <el-button
                type="success"
                :disabled="!projectId || endpoints.length === 0"
                :loading="generating"
                @click="generateCases"
              >
                预览并生成
              </el-button>
              <div class="gen-tip">
                导入接口后可一键 AI 生成用例（存入用例库）；
                将<a href="/knowledge" @click.prevent="router.push('/knowledge')">测试规范、历史缺陷</a>沉淀到知识库，生成质量更高。
              </div>
            </div>
          </div>
        </el-card>

        <el-card v-if="projectId" shadow="hover" style="margin-top: 16px">
          <template #header><div class="task-header"><span>用例生成任务</span><el-button size="small" :loading="tasksLoading" @click="loadGenerationTasks">刷新</el-button></div></template>
          <el-table :data="generationTasks" v-loading="tasksLoading" size="small" empty-text="暂无生成任务">
            <el-table-column label="状态" width="95"><template #default="{ row }"><el-tag :type="generationStatusType(row.status)">{{ generationStatusLabel(row.status) }}</el-tag></template></el-table-column>
            <el-table-column label="进度" min-width="150"><template #default="{ row }"><el-progress :percentage="row.progress || 0" :status="row.status === 'failed' ? 'exception' : row.status === 'completed' ? 'success' : undefined" /></template></el-table-column>
            <el-table-column label="范围" width="150"><template #default="{ row }">{{ row.endpoint_count }} 接口 / {{ row.generated_case_count || row.estimated_case_count }} 用例</template></el-table-column>
            <el-table-column label="引擎" width="110"><template #default="{ row }">{{ row.generation_engine === 'rule_degraded' ? '规则降级' : row.generation_engine === 'ai' ? 'AI' : '等待中' }}</template></el-table-column>
            <el-table-column label="时间" width="170"><template #default="{ row }">{{ formatTime(row.created_at) }}</template></el-table-column>
            <el-table-column label="操作" width="90"><template #default="{ row }"><el-button link type="primary" @click="showTask(row)">详情</el-button></template></el-table-column>
          </el-table>
        </el-card>
      </el-col>

      <!-- 右：已有资产 -->
      <el-col :xs="24" :lg="10">
        <el-card shadow="hover">
          <template #header>
            已有资产
            <el-button size="small" style="float: right" @click="loadAssets">刷新</el-button>
          </template>

          <el-tabs v-model="assetTab">
            <el-tab-pane label="文档" name="docs">
              <el-table :data="docs" v-loading="assetsLoading" size="small" border>
                <el-table-column prop="filename" label="文件名" show-overflow-tooltip />
                <el-table-column prop="doc_type" label="类型" width="90" />
                <el-table-column prop="status" label="状态" width="90">
                  <template #default="{ row }">
                    <el-tag :type="statusType(row.status)" size="small">{{ row.status }}</el-tag>
                  </template>
                </el-table-column>
                <el-table-column prop="endpoint_count" label="接口数" width="70" align="center" />
                <el-table-column label="操作" width="120" fixed="right">
                  <template #default="{ row }">
                    <el-button
                      size="small"
                      text
                      type="primary"
                      :loading="reparsingDocId === row.doc_id"
                      :disabled="!!reparsingDocId && reparsingDocId !== row.doc_id"
                      @click="reparse(row)"
                    >重解析</el-button>
                    <el-button size="small" text type="danger" @click="removeDoc(row)">删除</el-button>
                  </template>
                </el-table-column>
              </el-table>
            </el-tab-pane>
            <el-tab-pane label="接口资产" name="endpoints">
              <el-table :data="endpointRows" v-loading="assetsLoading" size="small" border max-height="420">
                <el-table-column label="方法" width="80">
                  <template #default="{ row }">
                    <el-tag :type="methodType(row.method)" size="small" effect="dark">{{ row.method }}</el-tag>
                  </template>
                </el-table-column>
                <el-table-column prop="path" label="路径" show-overflow-tooltip />
                <el-table-column prop="summary" label="说明" show-overflow-tooltip />
              </el-table>
            </el-tab-pane>
          </el-tabs>
        </el-card>
      </el-col>
    </el-row>

    <el-dialog v-model="previewVisible" title="确认生成范围" width="760px">
      <el-descriptions :column="3" border>
        <el-descriptions-item label="接口数量">{{ generationPreview?.endpoint_count || 0 }}</el-descriptions-item>
        <el-descriptions-item label="预计用例">约 {{ generationPreview?.estimated_case_count || 0 }} 条</el-descriptions-item>
        <el-descriptions-item label="已有用例">{{ generationPreview?.existing_case_count || 0 }} 条</el-descriptions-item>
      </el-descriptions>
      <el-alert v-for="warning in generationPreview?.warnings || []" :key="warning" type="warning" :closable="false" show-icon :title="warning" class="preview-warning" />
      <el-alert type="info" :closable="false" show-icon :title="generationPreview?.execution_mode || ''" class="preview-warning" />
      <el-table :data="generationPreview?.endpoints || []" size="small" max-height="320" border>
        <el-table-column prop="method" label="方法" width="85" /><el-table-column prop="path" label="路径" min-width="240" /><el-table-column prop="summary" label="说明" min-width="180" />
      </el-table>
      <template #footer><el-button @click="previewVisible = false">取消</el-button><el-button type="primary" :loading="submittingTask" @click="submitGenerationTask">提交异步任务</el-button></template>
    </el-dialog>

    <el-drawer v-model="taskDetailVisible" title="生成任务详情" size="min(620px, 94vw)">
      <el-descriptions v-if="activeTask" :column="1" border>
        <el-descriptions-item label="任务状态">{{ generationStatusLabel(activeTask.status) }}</el-descriptions-item>
        <el-descriptions-item label="生成范围">{{ activeTask.endpoint_count }} 个接口，预计 {{ activeTask.estimated_case_count }} 条</el-descriptions-item>
        <el-descriptions-item label="实际生成">{{ activeTask.generated_case_count }} 条</el-descriptions-item>
        <el-descriptions-item label="生成引擎">{{ activeTask.generation_engine }}</el-descriptions-item>
        <el-descriptions-item v-if="activeTask.degraded_reason" label="降级原因"><span class="warning-text">{{ activeTask.degraded_reason }}</span></el-descriptions-item>
        <el-descriptions-item v-if="activeTask.error_message" label="失败原因"><span class="error-text">{{ activeTask.error_message }}</span></el-descriptions-item>
      </el-descriptions>
      <el-result v-if="activeTask?.status === 'completed'" icon="success" title="生成完成" :sub-title="`已生成 ${activeTask.generated_case_count} 条草稿用例`"><template #extra><el-button type="primary" @click="router.push(`/case-library?project_id=${projectId}`)">进入用例管理与评审</el-button></template></el-result>
      <div v-if="activeTask?.generated_cases?.length" class="generated-preview">
        <div class="task-header">
          <strong>生成内容预览</strong>
          <span class="warning-text" v-if="activeTask.generated_cases_truncated">仅展示前 {{ activeTask.generated_cases.length }} 条</span>
        </div>
        <el-table :data="activeTask.generated_cases" size="small" border max-height="360">
          <el-table-column prop="title" label="用例标题" show-overflow-tooltip />
          <el-table-column prop="case_type" label="类型" width="100" />
          <el-table-column prop="priority" label="优先级" width="80" />
          <el-table-column prop="status" label="状态" width="90" />
        </el-table>
      </div>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onBeforeUnmount, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, type UploadFile } from 'element-plus'
import { caseApi, docApi, projectApi } from '@/api'
import ApiSpecTable from '@/components/ApiSpecTable.vue'
import { useAuthStore } from '@/stores'
import {
  loadCaseGenerationSnapshot,
  saveCaseGenerationSnapshot,
} from '@/utils/caseGenerationState'

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()
const userId = computed(() => authStore.user?.id || 'anonymous')

const projects = ref<any[]>([])
const projectId = ref<string>('')
const docType = ref<string>('')
const selectedFile = ref<File | null>(null)
const uploading = ref(false)

const currentDoc = ref<any>(null)
const endpoints = ref<any[]>([])
const selectedKeys = ref<string[]>([])
const degraded = ref(false)
const unparsedNotes = ref<string[]>([])
const overwrite = ref(true)

const assetTab = ref<'docs' | 'endpoints'>('docs')
const docs = ref<any[]>([])
const endpointRows = ref<any[]>([])
const assetsLoading = ref(false)
const restoringDoc = ref(false)
const reparsingDocId = ref('')
const parseFeedback = ref<{
  type: 'success' | 'warning' | 'error'
  title: string
  description?: string
} | null>(null)

const activeStep = computed(() => {
  if (currentDoc.value) {
    return selectedKeys.value.length > 0 ? 3 : 2
  }
  return selectedFile.value ? 1 : 0
})

function onFileChange(file: UploadFile) {
  // el-upload 可能为 UploadFile；取原始 File
  const raw = (file.raw as File) || (file as any)
  if (raw && raw.size > 20 * 1024 * 1024) {
    ElMessage.error('文件超过 20MB 上限')
    selectedFile.value = null
    return
  }
  selectedFile.value = raw
}

function clearFile() {
  selectedFile.value = null
  currentDoc.value = null
  endpoints.value = []
  selectedKeys.value = []
  updateStateQuery({ docId: '' })
  persistState()
}

async function uploadAndParse() {
  if (!projectId.value) return ElMessage.warning('请先选择项目')
  if (!selectedFile.value) return ElMessage.warning('请先选择文件')

  uploading.value = true
  currentDoc.value = null
  endpoints.value = []
  selectedKeys.value = []
  try {
    const up: any = await docApi.upload(selectedFile.value, projectId.value, docType.value || undefined)
    const docId = up?.data?.doc_id
    const pr: any = await docApi.parse(docId, { use_ai: true, max_endpoints: 200 })
    applyParseResult(pr?.data || {}, selectedFile.value.name)
    await loadAssets()
    ElMessage.success('解析完成')
  } catch (e: any) {
    // 拦截器已提示
  } finally {
    uploading.value = false
  }
}

async function importSelected() {
  if (!currentDoc.value?.doc_id) return
  if (selectedKeys.value.length === 0) return ElMessage.warning('请先勾选接口')
  await doImport({ endpoint_keys: selectedKeys.value, overwrite: overwrite.value })
}

async function importAll() {
  if (!currentDoc.value?.doc_id) return
  await doImport({ import_all: true, overwrite: overwrite.value })
}

async function doImport(payload: any) {
  try {
    const res: any = await docApi.import(currentDoc.value.doc_id, payload)
    const d = res?.data || {}
    ElMessage.success(`新增 ${d.imported} / 更新 ${d.updated} / 跳过 ${d.skipped} / 失败 ${d.failed}`)
    if (d.imported + d.updated > 0) {
      const docId = currentDoc.value.doc_id
      setTimeout(() => router.push(`/doc-review?doc_id=${docId}`), 800)
    }
    await loadAssets()
  } catch (e: any) {
    /* 拦截器已提示 */
  }
}

// R5：来源页生成用例 —— 解析导入的接口直接生成用例进用例库
const generating = ref(false)
const previewVisible = ref(false)
const generationPreview = ref<any>()
const submittingTask = ref(false)
const generationTasks = ref<any[]>([])
const tasksLoading = ref(false)
const taskDetailVisible = ref(false)
const activeTask = ref<any>()
let taskPollTimer: ReturnType<typeof setTimeout> | undefined

function persistState() {
  saveCaseGenerationSnapshot(userId.value, 'interface', projectId.value, {
    activeDocId: currentDoc.value?.doc_id,
    activeTaskId: activeTask.value?.id,
    selectedKeys: selectedKeys.value,
    docType: docType.value,
    overwrite: overwrite.value,
    assetTab: assetTab.value,
    taskDetailVisible: taskDetailVisible.value,
    generationPreview: generationPreview.value,
    previewVisible: previewVisible.value,
  })
}

function updateStateQuery(values: { docId?: string; taskId?: string } = {}) {
  router.replace({
    path: route.path,
    query: {
      ...route.query,
      project_id: projectId.value || undefined,
      doc_id: values.docId === undefined ? currentDoc.value?.doc_id : values.docId || undefined,
      task_id: values.taskId === undefined ? activeTask.value?.id : values.taskId || undefined,
    },
  })
}

function applyParseResult(data: any, filename?: string) {
  const parsed = data || {}
  currentDoc.value = {
    ...parsed,
    filename: parsed.filename || filename || currentDoc.value?.filename,
    degraded: parsed.degraded ?? parsed.parse_engine === 'rule_degraded',
    scanned: !!parsed.scanned,
  }
  endpoints.value = Array.isArray(parsed.endpoints)
    ? parsed.endpoints
    : Array.isArray(parsed.api_spec?.endpoints)
      ? parsed.api_spec.endpoints
      : []
  degraded.value = !!currentDoc.value.degraded
  unparsedNotes.value = parsed.unparsed_notes || (parsed.error ? [parsed.error] : [])
  selectedKeys.value = selectedKeys.value.filter(key =>
    endpoints.value.some((endpoint: any) => `${String(endpoint.method || '').toUpperCase()} ${endpoint.path || ''}` === key),
  )
  updateStateQuery({ docId: parsed.doc_id })
  persistState()
}

async function generateCases() {
  if (!projectId.value) {
    ElMessage.warning('请先选择项目')
    return
  }
  if (!currentDoc.value?.doc_id) {
    ElMessage.warning('请先解析接口文档')
    return
  }
  generating.value = true
  try {
    // 第一步：导入全部接口（幂等——重复导入按 overwrite 更新），避免
    // 「只解析未导入 → 生成时查不到接口资产」的断链
    const impRes: any = await docApi.import(currentDoc.value.doc_id, { import_all: true, overwrite: overwrite.value })
    const imp = impRes?.data || {}
    ElMessage.success(`接口导入完成：新增 ${imp.imported ?? 0} / 更新 ${imp.updated ?? 0}`)
    await loadAssets()

    // 第二步：按项目生成用例（覆盖刚导入的接口）
    const endpointIds = Array.isArray(imp.endpoint_ids) ? imp.endpoint_ids : []
    if (endpointIds.length === 0) {
      ElMessage.warning('当前文档没有可用于生成用例的接口资产')
      return
    }
    const res: any = await caseApi.previewGeneration({
      project_id: projectId.value,
      endpoint_ids: endpointIds,
    })
    generationPreview.value = res?.data || {}
    previewVisible.value = true
    persistState()
  } catch {
    /* 拦截器已提示 */
  } finally {
    generating.value = false
  }
}

async function submitGenerationTask() {
  const endpointIds = (generationPreview.value?.endpoints || []).map((item: any) => item.id)
  if (!endpointIds.length) return ElMessage.warning('没有可提交的接口')
  submittingTask.value = true
  try {
    const response: any = await caseApi.createGenerationTask({
      project_id: projectId.value, endpoint_ids: endpointIds, source_doc_id: currentDoc.value?.doc_id,
    })
    previewVisible.value = false
    activeTask.value = response?.data
    taskDetailVisible.value = true
    updateStateQuery({ taskId: activeTask.value?.id })
    persistState()
    ElMessage.success('生成任务已提交，可离开页面，完成后会收到站内通知')
    await loadGenerationTasks()
  } finally { submittingTask.value = false }
}

function generationStatusLabel(value: string) { return ({ pending: '等待中', running: '生成中', completed: '已完成', failed: '失败' } as any)[value] || value }
function generationStatusType(value: string): any { return value === 'completed' ? 'success' : value === 'failed' ? 'danger' : value === 'running' ? 'warning' : 'info' }
function formatTime(value?: string) { return value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '—' }
async function showTask(task: any) {
  activeTask.value = task
  taskDetailVisible.value = true
  updateStateQuery({ taskId: task.id })
  persistState()
  await refreshActiveTask()
}
function scheduleTaskPoll() {
  if (taskPollTimer) clearTimeout(taskPollTimer)
  if (generationTasks.value.some(task => ['pending', 'running'].includes(task.status))
      || ['pending', 'running'].includes(activeTask.value?.status)) {
    taskPollTimer = setTimeout(loadGenerationTasks, 3000)
  }
}
async function refreshActiveTask() {
  if (!activeTask.value?.id) return
  const previousStatus = activeTask.value.status
  try {
    const response: any = await caseApi.generationTask(activeTask.value.id)
    activeTask.value = response?.data || activeTask.value
    if (previousStatus && previousStatus !== 'completed' && activeTask.value.status === 'completed') {
      ElMessage.success(`用例生成完成，共 ${activeTask.value.generated_case_count} 条`)
    }
    persistState()
  } catch {
    /* 全局拦截器已提示，列表轮询仍可继续 */
  }
}
async function loadGenerationTasks() {
  if (!projectId.value) { generationTasks.value = []; return }
  tasksLoading.value = true
  try {
    const response: any = await caseApi.generationTasks({ project_id: projectId.value, page: 1, page_size: 20 })
    generationTasks.value = response?.data?.items || []
    if (!activeTask.value?.id) {
      const running = generationTasks.value.find(item => ['pending', 'running'].includes(item.status))
      if (running) {
        activeTask.value = running
        taskDetailVisible.value = true
        updateStateQuery({ taskId: running.id })
      }
    }
    if (activeTask.value?.id) await refreshActiveTask()
  } finally { tasksLoading.value = false; scheduleTaskPoll() }
}

async function loadAssets() {
  if (!projectId.value) return
  assetsLoading.value = true
  try {
    const [dl, el] = await Promise.all([
      docApi.list({ project_id: projectId.value, page: 1, page_size: 50 }),
      docApi.listEndpoints({ project_id: projectId.value, page: 1, page_size: 200 }),
    ])
    docs.value = dl?.data?.items || []
    endpointRows.value = el?.data?.items || []
  } catch {
    /* ignore */
  } finally {
    assetsLoading.value = false
  }
}

async function onProjectChange() {
  currentDoc.value = null; endpoints.value = []; selectedKeys.value = []
  activeTask.value = undefined
  generationPreview.value = undefined
  router.replace({
    path: route.path,
    query: { ...route.query, project_id: projectId.value || undefined, doc_id: undefined, task_id: undefined },
  })
}

async function reparse(row: any) {
  reparsingDocId.value = row.doc_id
  parseFeedback.value = null
  try {
    const pr: any = await docApi.parse(row.doc_id, { use_ai: true })
    const result = pr?.data || {}
    applyParseResult(result, row.filename)
    await loadAssets()
    if (result.status === 'failed' || !endpoints.value.length) {
      parseFeedback.value = {
        type: 'warning',
        title: '重新解析完成，但没有产出可用接口',
        description: unparsedNotes.value.join('；') || '请检查文档内容或模型配置。',
      }
      ElMessage.warning('重新解析未产出可用接口')
    } else {
      parseFeedback.value = {
        type: result.degraded ? 'warning' : 'success',
        title: `重新解析完成，已展示 ${endpoints.value.length} 个接口`,
        description: result.degraded ? 'AI 不可用，本次展示的是规则降级结果。' : undefined,
      }
      ElMessage.success(`重新解析完成，共 ${endpoints.value.length} 个接口`)
    }
  } catch (error: any) {
    parseFeedback.value = {
      type: 'error',
      title: '重新解析失败',
      description: error?.response?.data?.detail || error?.message || '请稍后重试。',
    }
  } finally {
    reparsingDocId.value = ''
  }
}

async function removeDoc(row: any) {
  try {
    await docApi.remove(row.doc_id)
    ElMessage.success('已删除')
    if (currentDoc.value?.doc_id === row.doc_id) {
      currentDoc.value = null; endpoints.value = []; selectedKeys.value = []
      updateStateQuery({ docId: '' })
      persistState()
    }
    await loadAssets()
  } catch {
    /* ignore */
  }
}

function statusType(status: string): any {
  if (status === 'parsed') return 'success'
  if (status === 'parsing') return 'warning'
  if (status === 'failed') return 'danger'
  return 'info'
}

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

async function loadProjects() {
  try {
    const res: any = await projectApi.getList()
    const d = res?.data ?? res
    projects.value = Array.isArray(d) ? d : d?.list || d?.items || []
  } catch {
    projects.value = []
  }
}

function queryProjectId(): string {
  const value = route.query.project_id
  return Array.isArray(value) ? String(value[0] || '') : String(value || '')
}

function queryValue(name: 'doc_id' | 'task_id'): string {
  const value = route.query[name]
  return Array.isArray(value) ? String(value[0] || '') : String(value || '')
}

async function restoreState() {
  if (!projectId.value) return
  const snapshot = loadCaseGenerationSnapshot(userId.value, 'interface', projectId.value)
  docType.value = snapshot.docType ?? docType.value
  overwrite.value = snapshot.overwrite ?? overwrite.value
  assetTab.value = snapshot.assetTab || assetTab.value
  selectedKeys.value = snapshot.selectedKeys || []
  generationPreview.value = snapshot.generationPreview
  previewVisible.value = !!snapshot.previewVisible && !!snapshot.generationPreview

  const docId = queryValue('doc_id') || snapshot.activeDocId || ''
  if (docId) {
    restoringDoc.value = true
    try {
      const response: any = await docApi.get(docId)
      const data = response?.data
      if (data && data.project_id === projectId.value) applyParseResult(data)
    } catch {
      currentDoc.value = null
      endpoints.value = []
      selectedKeys.value = []
    } finally {
      restoringDoc.value = false
    }
  }

  const taskId = queryValue('task_id') || snapshot.activeTaskId || ''
  if (taskId) {
    activeTask.value = { id: taskId, status: 'pending' }
    taskDetailVisible.value = snapshot.taskDetailVisible ?? true
    await refreshActiveTask()
    if (!queryValue('task_id')) updateStateQuery({ taskId })
  }
  persistState()
}

watch(
  () => route.query.project_id,
  async () => {
    const id = queryProjectId()
    if (!id || id === projectId.value) return
    projectId.value = id
    currentDoc.value = null
    endpoints.value = []
    selectedKeys.value = []
    await Promise.all([loadAssets(), loadGenerationTasks()])
    await restoreState()
  },
)

watch(
  [docType, overwrite, assetTab, selectedKeys, previewVisible, taskDetailVisible],
  persistState,
  { deep: true },
)

onMounted(async () => {
  await loadProjects()
  const id = queryProjectId()
  if (id) {
    projectId.value = id
    await Promise.all([loadAssets(), loadGenerationTasks()])
    await restoreState()
  }
})
onBeforeUnmount(() => { if (taskPollTimer) clearTimeout(taskPollTimer) })
</script>

<style scoped>
.gen-tip {
  margin-top: 8px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  line-height: 1.8;
}
.gen-tip a {
  color: var(--el-color-primary);
  text-decoration: none;
}
.actions {
  margin-top: 12px;
  display: flex;
  gap: 12px;
}
.steps {
  margin-top: var(--app-sp-5);
}
.notes {
  margin-bottom: 12px;
}
.import-bar {
  margin-top: 16px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  padding: 12px;
  background: var(--el-fill-color-light);
  border-radius: 6px;
}
.task-header { display: flex; align-items: center; justify-content: space-between; }
.preview-warning { margin: 12px 0; }
.warning-text { color: var(--el-color-warning-dark-2); white-space: pre-wrap; }
.error-text { color: var(--el-color-danger); white-space: pre-wrap; }
.generated-preview { margin-top: 18px; display: grid; gap: 10px; }
</style>
