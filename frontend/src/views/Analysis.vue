<template>
  <div class="analysis-page">
    <!-- Top action bar -->
    <el-card shadow="hover" class="action-card">
      <el-radio-group v-model="inputMode" style="margin-bottom: 16px">
        <el-radio-button value="project">已有项目代码（推荐）</el-radio-button>
        <el-radio-button value="remote">Git / SVN 远程仓库</el-radio-button>
        <el-radio-button value="files">本地文件 / Zip 包</el-radio-button>
      </el-radio-group>

      <div class="action-bar">
        <div class="left-section">
          <!-- 模式 1：已有项目代码 -->
          <template v-if="inputMode === 'project'">
            <div style="display: flex; flex-direction: column; gap: 8px">
              <div style="display: flex; gap: 12px; align-items: center; flex-wrap: wrap">
                <el-select
                  v-model="selectedProjectId"
                  placeholder="请选择已有项目"
                  style="width: 320px"
                  filterable
                >
                  <el-option
                    v-for="p in projectList"
                    :key="p.id"
                    :label="p.name"
                    :value="p.id"
                  >
                    <span style="float: left">{{ p.name }}</span>
                    <span style="float: right; color: #8492a6; font-size: 12px; margin-left: 12px">
                      {{ p.source_type?.toUpperCase() || '' }}
                    </span>
                  </el-option>
                </el-select>
                <el-tag v-if="selectedProject" :type="selectedProject.source_type === 'github' ? 'success' : 'warning'">
                  {{ selectedProject.source_type?.toUpperCase() }}
                </el-tag>
                <el-button
                  type="primary"
                  :loading="analyzing"
                  :disabled="!selectedProjectId"
                  @click="runProjectAnalysis"
                >
                  <el-icon><Search /></el-icon>
                  解析项目代码
                </el-button>
              </div>
              <div v-if="selectedProjectRepoUrl" style="font-size: 13px; color: #606266">
                关联仓库: <code class="mono-text">{{ selectedProjectRepoUrl }}</code>
              </div>
            </div>
          </template>

          <!-- 模式 2：Git / SVN 远程仓库 -->
          <template v-else-if="inputMode === 'remote'">
            <div style="display: flex; flex-direction: column; gap: 10px; width: 100%">
              <div style="display: flex; gap: 10px; align-items: center; flex-wrap: wrap">
                <el-select v-model="remoteForm.source_type" style="width: 110px">
                  <el-option label="GitHub" value="github" />
                  <el-option label="SVN" value="svn" />
                </el-select>
                <el-input
                  v-if="remoteForm.source_type === 'github'"
                  v-model="remoteForm.repo_url"
                  placeholder="https://github.com/owner/repo"
                  style="width: 320px"
                  clearable
                />
                <el-input
                  v-else
                  v-model="remoteForm.svn_url"
                  placeholder="svn:// or http://svn.example.com/repo"
                  style="width: 320px"
                  clearable
                />
                <el-input
                  v-if="remoteForm.source_type === 'github'"
                  v-model="remoteForm.branch"
                  placeholder="分支 (默认 main)"
                  style="width: 130px"
                  clearable
                />
                <el-input
                  v-if="remoteForm.source_type === 'github'"
                  v-model="remoteForm.github_token"
                  type="password"
                  show-password
                  placeholder="Token (公开仓库留空)"
                  style="width: 180px"
                  clearable
                />
                <template v-else>
                  <el-input
                    v-model="remoteForm.svn_username"
                    placeholder="SVN 用户名"
                    style="width: 130px"
                    clearable
                  />
                  <el-input
                    v-model="remoteForm.svn_password"
                    type="password"
                    show-password
                    placeholder="SVN 密码"
                    style="width: 140px"
                    clearable
                  />
                </template>
                <el-button
                  type="primary"
                  :loading="analyzing"
                  :disabled="!remoteFormValid"
                  @click="runRemoteAnalysis"
                >
                  <el-icon><Search /></el-icon>
                  拉取并解析
                </el-button>
              </div>
              <div style="font-size: 12px; color: #909399">
                * 公开开源仓库直接输入地址即可免 Token 拉取与解析；私有仓库请填写对应访问凭据。
              </div>
            </div>
          </template>

          <!-- 模式 3：文件 / Zip 上传 -->
          <template v-else>
            <el-upload
              v-model:file-list="uploadFileList"
              :auto-upload="false"
              multiple
              :limit="50"
              accept=".py,.js,.jsx,.ts,.tsx,.java,.kt,.go,.rb,.php,.cs,.cpp,.c,.h,.zip"
              drag
              class="upload-area"
            >
              <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
              <div class="el-upload__text">
                拖入源文件 / 代码 zip 包，或<em>点击选择</em>
              </div>
              <template #tip>
                <div class="el-upload__tip">
                  支持 .py / .js / .ts / .java / .go / .rb / .php 等源文件；也支持 .zip 压缩包
                </div>
              </template>
            </el-upload>
            <el-button
              type="primary"
              :loading="analyzing"
              :disabled="uploadFileList.length === 0"
              @click="runUploadAnalysis"
            >
              <el-icon><Upload /></el-icon>
              发起上传解析
            </el-button>
          </template>
        </div>
        <div v-if="analysisResult" class="right-section">
          <el-tag type="success">API 总数: {{ analysisResult.total_apis }}</el-tag>
          <el-tag v-if="analysisResult.tech_stack?.stack" style="margin-left: 8px" type="info">
            {{ analysisResult.tech_stack.stack }}
          </el-tag>
        </div>
      </div>
    </el-card>

    <!-- Loading state -->
    <el-card v-if="analyzing" shadow="hover" class="loading-card">
      <el-skeleton :rows="8" animated />
      <div class="loading-text">
        <el-icon class="is-loading"><Loading /></el-icon>
        正在进行 AI 代码解析，这可能需要几分钟...
      </div>
    </el-card>

    <!-- Empty state -->
    <el-empty v-if="!analyzing && !analysisResult" description="输入代码路径并发起解析" />

    <!-- Results -->
    <div v-if="!analyzing && analysisResult" class="results-container">
      <!-- Tech stack info -->
      <el-card shadow="hover" class="stack-card">
        <template #header>
          <span>技术栈信息</span>
        </template>
        <el-descriptions :column="4" border>
          <el-descriptions-item label="语言">
            <el-tag>{{ analysisResult.tech_stack?.language || 'N/A' }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="框架">
            <el-tag type="success">{{ analysisResult.tech_stack?.framework || 'N/A' }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="技术栈标识">
            <el-tag type="info">{{ analysisResult.tech_stack?.stack || 'unknown' }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="置信度">
            <el-progress
              :percentage="Math.round((analysisResult.tech_stack?.confidence || 0) * 100)"
              :color="confidenceColor"
              style="width: 150px"
            />
          </el-descriptions-item>
        </el-descriptions>
      </el-card>

      <!-- Tabs -->
      <el-card shadow="hover" class="tabs-card">
        <el-tabs v-model="activeTab">
          <!-- API List -->
          <el-tab-pane label="接口清单" name="apis">
            <el-table :data="analysisResult.apis || []" stripe style="width: 100%" max-height="600">
              <el-table-column type="index" width="50" />
              <el-table-column label="HTTP 方法" width="100">
                <template #default="{ row }">
                  <el-tag :type="methodTagType(row.http_method)" size="small">
                    {{ row.http_method?.toUpperCase() || 'GET' }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="path" label="路径" min-width="250" show-overflow-tooltip />
              <el-table-column label="参数概要" min-width="200">
                <template #default="{ row }">
                  <span v-if="!row.params || row.params.length === 0" class="text-muted">无参数</span>
                  <el-tag
                    v-for="p in (row.params || []).slice(0, 3)"
                    :key="p.name"
                    size="small"
                    class="param-tag"
                  >
                    {{ p.type }}: {{ p.name }}
                  </el-tag>
                  <span v-if="(row.params || []).length > 3" class="text-muted">
                    +{{ row.params.length - 3 }}
                  </span>
                </template>
              </el-table-column>
              <el-table-column label="认证" width="80">
                <template #default="{ row }">
                  <el-tag :type="row.auth_required ? 'danger' : 'info'" size="small">
                    {{ row.auth_required ? '需要' : '无需' }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="method_name" label="方法名" width="180" show-overflow-tooltip />
              <el-table-column prop="file" label="文件" min-width="200" show-overflow-tooltip />
            </el-table>
          </el-tab-pane>

          <!-- Business Modules -->
          <el-tab-pane label="业务模块" name="modules">
            <el-empty v-if="!hasBusinessModules" description="暂无业务模块分析数据" />
            <el-collapse v-else v-model="expandedModules">
              <el-collapse-item
                v-for="(mod, idx) in businessModules"
                :key="idx"
                :name="idx"
                :title="mod.name || `模块 ${idx + 1}`"
              >
                <div class="module-detail">
                  <p v-if="mod.description" class="module-desc">{{ mod.description }}</p>
                  <div v-if="mod.apis && mod.apis.length" class="module-apis">
                    <el-tag
                      v-for="api in mod.apis"
                      :key="api.path || api"
                      size="small"
                      class="param-tag"
                    >
                      {{ api.http_method?.toUpperCase() || '' }} {{ api.path || api }}
                    </el-tag>
                  </div>
                  <div v-if="mod.business_logic" class="module-section">
                    <strong>业务逻辑:</strong> {{ mod.business_logic }}
                  </div>
                  <div v-if="mod.dependencies && mod.dependencies.length" class="module-section">
                    <strong>依赖:</strong>
                    <el-tag
                      v-for="dep in mod.dependencies"
                      :key="dep"
                      size="small"
                      type="info"
                      class="param-tag"
                    >
                      {{ dep }}
                    </el-tag>
                  </div>
                </div>
              </el-collapse-item>
            </el-collapse>
          </el-tab-pane>

          <!-- Dependency Graph -->
          <el-tab-pane label="依赖图" name="graph">
            <div ref="graphRef" class="graph-container" />
            <el-empty v-if="!hasGraphData" description="暂无依赖关系数据" />
          </el-tab-pane>

          <!-- Risk Areas -->
          <el-tab-pane label="风险区域" name="risks">
            <el-empty v-if="!hasRiskAreas" description="暂无风险区域数据" />
            <div v-else class="risk-list">
              <el-alert
                v-for="(risk, idx) in riskAreas"
                :key="idx"
                :title="risk.title || risk.name || `风险 ${idx + 1}`"
                :type="riskSeverity(risk)"
                :description="risk.description || risk.detail || ''"
                show-icon
                :closable="false"
                class="risk-item"
              />
            </div>
          </el-tab-pane>

          <!-- AI Analysis Raw -->
          <el-tab-pane label="AI 分析详情" name="ai">
            <el-empty v-if="!analysisResult.ai_analysis" description="暂无 AI 分析数据" />
            <pre v-else class="json-viewer">{{ JSON.stringify(analysisResult.ai_analysis, null, 2) }}</pre>
          </el-tab-pane>
        </el-tabs>
      </el-card>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, nextTick, watch, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { Search, Loading, UploadFilled, Upload } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { analysisApi, projectApi } from '@/api'
import type { UploadUserFile, UploadRawFile } from 'element-plus'

const route = useRoute()
const inputMode = ref<'project' | 'remote' | 'files'>('project')
const analyzing = ref(false)
const analysisResult = ref<any>(null)
const activeTab = ref('apis')
const expandedModules = ref<number[]>([])
const graphRef = ref<HTMLElement>()
const uploadFileList = ref<UploadUserFile[]>([])

// 项目模式状态
const projectList = ref<any[]>([])
const selectedProjectId = ref('')
const selectedProject = computed(() =>
  projectList.value.find((p) => p.id === selectedProjectId.value)
)
const selectedProjectRepoUrl = computed(() => {
  const cfg = selectedProject.value?.source_config || {}
  return cfg.repo_url || cfg.svn_url || ''
})

// 远程仓库模式状态
const remoteForm = ref({
  source_type: 'github',
  repo_url: '',
  branch: 'main',
  commit_sha: '',
  github_token: '',
  svn_url: '',
  svn_username: '',
  svn_password: '',
  svn_revision: '',
})

const remoteFormValid = computed(() => {
  if (remoteForm.value.source_type === 'github') {
    return !!remoteForm.value.repo_url?.trim()
  }
  return !!remoteForm.value.svn_url?.trim()
})

// Computed properties
const hasBusinessModules = computed(() => {
  const modules = analysisResult.value?.ai_analysis?.business_modules
  return Array.isArray(modules) && modules.length > 0
})

const businessModules = computed(() => {
  return analysisResult.value?.ai_analysis?.business_modules || []
})

const hasRiskAreas = computed(() => {
  const risks = analysisResult.value?.ai_analysis?.risk_areas
  return Array.isArray(risks) && risks.length > 0
})

const riskAreas = computed(() => {
  return analysisResult.value?.ai_analysis?.risk_areas || []
})

const hasGraphData = computed(() => {
  const modules = analysisResult.value?.ai_analysis?.business_modules
  return Array.isArray(modules) && modules.length > 0
})

const confidenceColor = computed(() => {
  const conf = analysisResult.value?.tech_stack?.confidence || 0
  if (conf >= 0.8) return '#67c23a'
  if (conf >= 0.5) return '#e6a23c'
  return '#f56c6c'
})

// Methods
function methodTagType(method: string): string {
  const map: Record<string, string> = {
    get: 'success',
    post: 'primary',
    put: 'warning',
    delete: 'danger',
    patch: 'info',
  }
  return map[(method || '').toLowerCase()] || 'info'
}

function riskSeverity(risk: any): 'error' | 'warning' | 'info' {
  const level = risk.severity || risk.level || ''
  if (level.toLowerCase().includes('high') || level.toLowerCase().includes('p0')) return 'error'
  if (level.toLowerCase().includes('medium') || level.toLowerCase().includes('p1')) return 'warning'
  return 'info'
}

async function loadProjects() {
  try {
    const res: any = await projectApi.getList()
    projectList.value = res?.data?.list || []
    if (route.query.project_id) {
      selectedProjectId.value = route.query.project_id as string
    } else if (projectList.value.length > 0 && !selectedProjectId.value) {
      selectedProjectId.value = projectList.value[0].id
    }
  } catch {
    projectList.value = []
  }
}

onMounted(() => {
  loadProjects()
})

async function runProjectAnalysis() {
  if (!selectedProjectId.value) {
    ElMessage.warning('请选择项目')
    return
  }

  analyzing.value = true
  analysisResult.value = null
  activeTab.value = 'apis'

  try {
    const res: any = await analysisApi.project(selectedProjectId.value)
    analysisResult.value = res?.data || res
    ElMessage.success(
      `项目「${selectedProject.value?.name || ''}」解析完成，识别到 ${analysisResult.value?.total_apis || 0} 个 API 接口` +
        (analysisResult.value?.tech_stack?.stack ? `（栈：${analysisResult.value.tech_stack.stack}）` : '')
    )
    if (hasBusinessModules.value) {
      expandedModules.value = [0]
    }
    await nextTick()
    if (hasGraphData.value) {
      renderDependencyGraph()
    }
  } catch (err: any) {
    ElMessage.error('项目代码解析失败: ' + (err.response?.data?.detail || err.message))
  } finally {
    analyzing.value = false
  }
}

async function runRemoteAnalysis() {
  if (!remoteFormValid.value) {
    ElMessage.warning('请输入仓库地址')
    return
  }

  analyzing.value = true
  analysisResult.value = null
  activeTab.value = 'apis'

  try {
    const payload = {
      ...remoteForm.value,
      repo_url: remoteForm.value.repo_url.trim(),
      svn_url: remoteForm.value.svn_url.trim(),
      branch: remoteForm.value.branch.trim() || 'main',
      github_token: remoteForm.value.github_token.trim() || undefined,
    }
    const res: any = await analysisApi.remote(payload)
    analysisResult.value = res?.data || res
    ElMessage.success(
      `远程仓库拉取解析完成，识别到 ${analysisResult.value?.total_apis || 0} 个 API 接口` +
        (analysisResult.value?.tech_stack?.stack ? `（栈：${analysisResult.value.tech_stack.stack}）` : '')
    )
    if (hasBusinessModules.value) {
      expandedModules.value = [0]
    }
    await nextTick()
    if (hasGraphData.value) {
      renderDependencyGraph()
    }
  } catch (err: any) {
    ElMessage.error('远程拉取解析失败: ' + (err.response?.data?.detail || err.message))
  } finally {
    analyzing.value = false
  }
}

async function runUploadAnalysis() {
  if (uploadFileList.value.length === 0) {
    ElMessage.warning('请先选择文件或 zip 包')
    return
  }
  analyzing.value = true
  analysisResult.value = null
  activeTab.value = 'apis'
  try {
    // 拆 files vs zip
    const formData = new FormData()
    const zipItem = uploadFileList.value.find((f) => f.name?.toLowerCase().endsWith('.zip'))
    const fileItems = uploadFileList.value.filter((f) => !f.name?.toLowerCase().endsWith('.zip'))
    for (const item of fileItems) {
      if (item.raw) formData.append('files', item.raw as UploadRawFile)
    }
    if (zipItem && zipItem.raw) {
      formData.append('zip_file', zipItem.raw as UploadRawFile)
    }
    const res: any = await analysisApi.upload(formData)
    analysisResult.value = res?.data || res
    ElMessage.success(
      `上传解析完成，识别到 ${analysisResult.value?.total_apis || 0} 个 API 接口` +
        (analysisResult.value?.tech_stack?.stack ? `（栈：${analysisResult.value.tech_stack.stack}）` : '')
    )
    if (hasBusinessModules.value) {
      expandedModules.value = [0]
    }
    await nextTick()
    if (hasGraphData.value) {
      renderDependencyGraph()
    }
  } catch (err: any) {
    ElMessage.error('上传解析失败: ' + (err.response?.data?.detail || err.message))
  } finally {
    analyzing.value = false
  }
}

function renderDependencyGraph() {
  if (!graphRef.value) return

  const modules = businessModules.value
  if (!modules || modules.length === 0) return

  // Simple graph rendering using basic SVG
  const nodes = modules.map((m: any, i: number) => ({
    id: i,
    name: m.name || `Module ${i + 1}`,
    x: 100 + (i % 4) * 200,
    y: 80 + Math.floor(i / 4) * 150,
  }))

  const edges: Array<{ source: number; target: number }> = []
  modules.forEach((m: any, i: number) => {
    if (m.dependencies) {
      m.dependencies.forEach((dep: string) => {
        const targetIdx = modules.findIndex(
          (mod: any) => mod.name === dep || mod.name?.includes(dep)
        )
        if (targetIdx >= 0 && targetIdx !== i) {
          edges.push({ source: i, target: targetIdx })
        }
      })
    }
  })

  // Render simple SVG graph
  const svgWidth = Math.max(800, Math.ceil(nodes.length / 4) * 200 + 100)
  const svgHeight = Math.max(300, Math.ceil(nodes.length / 4) * 150 + 50)

  let svg = `<svg width="${svgWidth}" height="${svgHeight}" style="width: 100%; height: 500px">`
  
  // Draw edges
  edges.forEach((edge: any) => {
    const s = nodes[edge.source]
    const t = nodes[edge.target]
    svg += `<line x1="${s.x}" y1="${s.y}" x2="${t.x}" y2="${t.y}" stroke="#a0cfff" stroke-width="2" marker-end="url(#arrow)" />`
  })

  // Arrow marker
  svg += `<defs><marker id="arrow" markerWidth="10" markerHeight="10" refX="20" refY="3" orient="auto"><path d="M0,0 L0,6 L6,3 Z" fill="#a0cfff"/></marker></defs>`

  // Draw nodes
  nodes.forEach((node: any) => {
    svg += `<g transform="translate(${node.x}, ${node.y})">`
    svg += `<rect x="-60" y="-20" width="120" height="40" rx="8" fill="#ecf5ff" stroke="#409eff" stroke-width="1.5"/>`
    svg += `<text x="0" y="5" text-anchor="middle" font-size="13" fill="#303133">${node.name}</text>`
    svg += `</g>`
  })

  svg += `</svg>`
  graphRef.value.innerHTML = svg
}

// Watch tab changes to render graph
watch(activeTab, (val) => {
  if (val === 'graph' && hasGraphData.value) {
    nextTick(() => renderDependencyGraph())
  }
})
</script>

<style scoped>
.analysis-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.action-card .action-bar {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
}

.left-section {
  display: flex;
  gap: 12px;
  align-items: center;
  flex: 1;
}

.upload-area {
  width: 400px;
  margin-right: 8px;
}

.upload-area :deep(.el-upload-dragger) {
  padding: 12px;
}

.loading-card {
  text-align: center;
}

.loading-text {
  margin-top: 16px;
  color: #909399;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
}

.results-container {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.param-tag {
  margin: 2px 4px 2px 0;
}

.text-muted {
  color: #909399;
  font-size: 12px;
}

.module-detail {
  padding: 8px 0;
}

.module-desc {
  color: #606266;
  margin-bottom: 12px;
}

.module-section {
  margin-top: 8px;
}

.module-section strong {
  color: #303133;
  margin-right: 8px;
}

.graph-container {
  width: 100%;
  min-height: 500px;
  overflow: auto;
  border: 1px solid #ebeef5;
  border-radius: 4px;
  padding: 16px;
}

.risk-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.json-viewer {
  background: #f5f7fa;
  border: 1px solid #ebeef5;
  border-radius: 4px;
  padding: 16px;
  font-size: 13px;
  line-height: 1.6;
  overflow: auto;
  max-height: 600px;
  white-space: pre-wrap;
  word-break: break-all;
}
</style>
