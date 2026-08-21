<template>
  <div class="req-parse">
    <el-row :gutter="16">
      <!-- 左：上传 + 解析 -->
      <el-col :xs="24" :lg="14">
        <el-card shadow="hover">
          <template #header>1. 选择项目并上传需求文档（PRD）</template>

          <el-form label-width="100px">
            <el-form-item label="项目" required>
              <el-select v-model="projectId" placeholder="选择项目" filterable style="width: 100%">
                <el-option v-for="p in projects" :key="p.id" :label="p.name" :value="p.id" />
              </el-select>
            </el-form-item>
            <el-form-item label="使用 AI">
              <el-switch v-model="useAi" active-text="AI 结构化" inactive-text="仅规则" />
              <span class="hint">未配模型时自动降级为规则抽取（编号/功能标题）</span>
            </el-form-item>
          </el-form>

          <el-upload
            drag
            :auto-upload="false"
            :limit="1"
            :show-file-list="true"
            accept=".docx,.pdf,.txt"
            :on-change="onFileChange"
            :on-exceed="() => ElMessage.warning('每次仅可上传一个文件')"
          >
            <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
            <div class="el-upload__text">拖入文件或 <em>点击选择</em></div>
            <template #tip>
              <div class="el-upload__tip">
                支持 Word(docx) / PDF / 纯文本(txt)，单文件 ≤ 20MB。AI 会从 PRD 中抽取功能点、验收标准与建议测试点。
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
        </el-card>

        <el-card shadow="hover" v-if="currentDoc" style="margin-top: 16px">
          <template #header>
            2. 解析出的需求（{{ requirements.length }} 条）
            <el-tag size="small" style="margin-left: 8px">{{ currentDoc.parse_engine }}</el-tag>
          </template>

          <el-table :data="requirements" v-loading="uploading" size="small" border stripe max-height="520">
            <el-table-column prop="rid" label="编号" width="90" />
            <el-table-column prop="title" label="需求标题" show-overflow-tooltip />
            <el-table-column prop="category" label="类别" width="100">
              <template #default="{ row }">
                <el-tag size="small">{{ catLabel(row.category) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="priority" label="优先级" width="80" align="center">
              <template #default="{ row }">
                <el-tag :type="prioType(row.priority)" size="small" effect="dark">{{ row.priority }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column type="expand" label="明细" width="60">
              <template #default="{ row }">
                <div class="detail">
                  <div v-if="row.description"><b>描述：</b>{{ row.description }}</div>
                  <div v-if="row.acceptance_criteria?.length">
                    <b>验收标准：</b>
                    <ul><li v-for="(a, i) in row.acceptance_criteria" :key="i">{{ a }}</li></ul>
                  </div>
                  <div v-if="row.related_modules?.length"><b>关联模块：</b>{{ row.related_modules.join('、') }}</div>
                  <div v-if="row.test_points?.length">
                    <b>建议测试点：</b>
                    <ul><li v-for="(t, i) in row.test_points" :key="i">{{ t }}</li></ul>
                  </div>
                </div>
              </template>
            </el-table-column>
          </el-table>

          <div class="import-bar">
            <el-button type="success" :loading="genLoading" :disabled="requirements.length === 0" @click="openGen">
              一键生成测试用例
            </el-button>
            <span class="hint">将基于上述需求调用 AI 生成功能 / 边界 / 异常用例</span>
          </div>
        </el-card>
      </el-col>

      <!-- 右：已有需求文档 -->
      <el-col :xs="24" :lg="10">
        <el-card shadow="hover">
          <template #header>
            已有需求文档
            <el-button size="small" style="float: right" @click="loadDocs">刷新</el-button>
          </template>
          <el-table :data="docs" v-loading="docsLoading" size="small" border empty-text="暂无需求文档">
            <el-table-column prop="filename" label="文件名" show-overflow-tooltip />
            <el-table-column prop="status" label="状态" width="90">
              <template #default="{ row }">
                <el-tag :type="statusType(row.status)" size="small">{{ row.status }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="total" label="需求数" width="70" align="center" />
            <el-table-column label="操作" width="120" fixed="right">
              <template #default="{ row }">
                <el-button size="small" text type="primary" @click="viewDoc(row)">查看</el-button>
                <el-button size="small" text type="danger" @click="removeDoc(row)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>
    </el-row>

    <!-- 生成用例对话框 -->
    <el-dialog v-model="genVisible" title="生成测试用例" width="460px">
      <el-form label-width="110px">
        <el-form-item label="关联测试任务">
          <el-input v-model="testRunId" placeholder="可选：填写测试任务 ID 以直接落库为用例" />
        </el-form-item>
        <el-form-item label="使用 AI">
          <el-switch v-model="genUseAi" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="genVisible = false">取消</el-button>
        <el-button type="primary" :loading="genLoading" @click="doGenerate">生成</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage, type UploadFile } from 'element-plus'
import { requirementApi, projectApi } from '@/api'

const projects = ref<any[]>([])
const projectId = ref<string>('')
const useAi = ref(true)
const selectedFile = ref<File | null>(null)
const uploading = ref(false)

const currentDoc = ref<any>(null)
const requirements = ref<any[]>([])

const docs = ref<any[]>([])
const docsLoading = ref(false)

const genVisible = ref(false)
const genLoading = ref(false)
const genUseAi = ref(true)
const testRunId = ref<string>('')

function catLabel(c: string): string {
  return (
    { functional: '功能', non_functional: '非功能', interface: '接口', security: '安全' }[c] || c
  )
}
function prioType(p: string): any {
  return p === 'P0' ? 'danger' : p === 'P1' ? 'warning' : p === 'P2' ? 'primary' : 'info'
}
function statusType(s: string): any {
  if (s === 'parsed') return 'success'
  if (s === 'parsing') return 'warning'
  if (s === 'failed') return 'danger'
  return 'info'
}

function onFileChange(file: UploadFile) {
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
  requirements.value = []
}

async function uploadAndParse() {
  if (!projectId.value) return ElMessage.warning('请先选择项目')
  if (!selectedFile.value) return ElMessage.warning('请先选择文件')
  uploading.value = true
  currentDoc.value = null
  requirements.value = []
  try {
    const up: any = await requirementApi.upload(selectedFile.value, projectId.value, useAi.value)
    const docId = up?.data?.id
    const detail: any = await requirementApi.get(docId)
    currentDoc.value = detail?.data || {}
    requirements.value = currentDoc.value.requirements?.items || []
    await loadDocs()
    ElMessage.success(`解析完成，共 ${requirements.value.length} 条需求`)
  } catch (e: any) {
    /* 拦截器已提示 */
  } finally {
    uploading.value = false
  }
}

function openGen() {
  genVisible.value = true
}
async function doGenerate() {
  if (!currentDoc.value?.id) return
  genLoading.value = true
  try {
    const res: any = await requirementApi.generateCases(currentDoc.value.id, {
      use_ai: genUseAi.value,
      test_run_id: testRunId.value || undefined,
    })
    const d = res?.data || {}
    ElMessage.success(`生成 ${d.total} 条用例` + (d.created ? `，已落库 ${d.created} 条` : ''))
    genVisible.value = false
  } catch (e: any) {
    /* 拦截器已提示 */
  } finally {
    genLoading.value = false
  }
}

async function loadDocs() {
  if (!projectId.value) return
  docsLoading.value = true
  try {
    const res: any = await requirementApi.list({ project_id: projectId.value })
    docs.value = res?.data || []
  } catch {
    docs.value = []
  } finally {
    docsLoading.value = false
  }
}
async function viewDoc(row: any) {
  try {
    const detail: any = await requirementApi.get(row.id)
    currentDoc.value = detail?.data || {}
    requirements.value = currentDoc.value.requirements?.items || []
    projectId.value = row.project_id || projectId.value
  } catch {
    /* ignore */
  }
}
async function removeDoc(row: any) {
  try {
    await requirementApi.remove(row.id)
    ElMessage.success('已删除')
    await loadDocs()
  } catch {
    /* ignore */
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
.hint {
  color: #909399;
  font-size: 12px;
  margin-left: 8px;
}
.import-bar {
  margin-top: 16px;
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  padding: 12px;
  background: #f5f7fa;
  border-radius: 6px;
}
.detail {
  font-size: 13px;
  line-height: 1.7;
}
.detail ul {
  margin: 4px 0 4px 18px;
  padding: 0;
}
</style>
