<template>
  <div class="doc-parser">
    <el-row :gutter="16">
      <!-- 左：上传 + 解析 -->
      <el-col :xs="24" :lg="14">
        <el-card shadow="hover">
          <template #header>1. 选择项目并上传接口文档</template>

          <el-form label-width="100px">
            <el-form-item label="项目" required>
              <el-select v-model="projectId" placeholder="选择项目" filterable style="width: 100%">
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

        <el-card shadow="hover" v-if="currentDoc" style="margin-top: 16px">
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
            </div>
          </div>
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
                    <el-button size="small" text type="primary" @click="reparse(row)">重解析</el-button>
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
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, type UploadFile } from 'element-plus'
import { docApi, projectApi } from '@/api'
import ApiSpecTable from '@/components/ApiSpecTable.vue'

const router = useRouter()

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

const activeStep = computed(() => {
  if (!selectedFile.value) return 0
  if (!currentDoc.value) return 1
  if (selectedKeys.value.length === 0 && endpoints.value.length > 0) return 2
  return 3
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
    currentDoc.value = pr?.data || {}
    endpoints.value = currentDoc.value.endpoints || []
    degraded.value = !!currentDoc.value.degraded
    unparsedNotes.value = currentDoc.value.unparsed_notes || []
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

async function reparse(row: any) {
  try {
    const pr: any = await docApi.parse(row.doc_id, { use_ai: true })
    ElMessage.success('重新解析完成')
    await loadAssets()
  } catch {
    /* ignore */
  }
}

async function removeDoc(row: any) {
  try {
    await docApi.remove(row.doc_id)
    ElMessage.success('已删除')
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

onMounted(() => {
  loadProjects()
})
</script>

<style scoped>
.actions {
  margin-top: 12px;
  display: flex;
  gap: 12px;
}
.steps {
  margin-top: 20px;
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
  background: #f5f7fa;
  border-radius: 6px;
}
</style>
