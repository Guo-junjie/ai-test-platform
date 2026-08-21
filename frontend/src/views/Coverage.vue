<template>
  <div class="coverage">
    <el-row :gutter="16">
      <!-- 左：上传 + 报告列表 -->
      <el-col :xs="24" :lg="14">
        <el-card shadow="hover">
          <template #header>1. 上传覆盖率报告（coverage.py / JaCoCo / istanbul）</template>

          <el-form label-width="100px">
            <el-form-item label="项目" required>
              <el-select v-model="projectId" placeholder="选择项目" filterable style="width: 100%" @change="loadReports">
                <el-option v-for="p in projects" :key="p.id" :label="p.name" :value="p.id" />
              </el-select>
            </el-form-item>
            <el-form-item label="工具" required>
              <el-select v-model="tool" style="width: 100%">
                <el-option label="coverage.py (Python)" value="coverage.py" />
                <el-option label="JaCoCo (Java)" value="jacoco" />
                <el-option label="istanbul / nyc (Node)" value="istanbul" />
                <el-option label="Cobertura (通用)" value="cobertura" />
              </el-select>
            </el-form-item>
            <el-form-item label="语言">
              <el-input v-model="language" placeholder="可选：python / java / javascript" />
            </el-form-item>
            <el-form-item label="关联任务">
              <el-input v-model="testRunId" placeholder="可选：测试任务 ID（自动采集时自动关联）" />
            </el-form-item>
          </el-form>

          <el-upload
            drag
            :auto-upload="false"
            :limit="1"
            :show-file-list="true"
            accept=".xml"
            :on-change="onFileChange"
            :on-exceed="() => ElMessage.warning('每次仅可上传一个文件')"
          >
            <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
            <div class="el-upload__text">拖入覆盖率 XML 或 <em>点击选择</em></div>
            <template #tip>
              <div class="el-upload__tip">
                coverage.py 执行 <code>coverage xml</code>、JaCoCo 执行 <code>jacoco:report</code> 生成 XML 后上传。
              </div>
            </template>
          </el-upload>

          <div class="actions">
            <el-button
              type="primary"
              :loading="uploading"
              :disabled="!projectId || !tool || !selectedFile"
              @click="uploadReport"
            >
              解析并入库
            </el-button>
            <el-button :disabled="!selectedFile" @click="clearFile">清除</el-button>
          </div>
        </el-card>

        <el-card shadow="hover" style="margin-top: 16px">
          <template #header>
            覆盖率报告
            <el-button size="small" style="float: right" @click="loadReports">刷新</el-button>
          </template>
          <el-table :data="reports" v-loading="loading" size="small" border empty-text="暂无覆盖率报告">
            <el-table-column prop="tool" label="工具" width="110" />
            <el-table-column label="行覆盖" width="100" align="center">
              <template #default="{ row }">
                <el-tag :type="rateType(row.line_rate)" effect="plain">{{ row.line_rate }}%</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="分支覆盖" width="100" align="center">
              <template #default="{ row }">
                <el-tag :type="rateType(row.branch_rate)" effect="plain">{{ row.branch_rate }}%</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="covered_lines" label="行(覆盖/总)" width="120" align="center">
              <template #default="{ row }">{{ row.covered_lines }}/{{ row.total_lines }}</template>
            </el-table-column>
            <el-table-column prop="source" label="来源" width="80" />
            <el-table-column label="操作" width="120" fixed="right">
              <template #default="{ row }">
                <el-button size="small" text type="primary" @click="viewReport(row)">明细</el-button>
                <el-button size="small" text type="danger" @click="removeReport(row)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>

      <!-- 右：明细 -->
      <el-col :xs="24" :lg="10">
        <el-card shadow="hover" v-if="detail">
          <template #header>
            报告明细
            <el-tag size="small" style="margin-left: 8px">{{ detail.tool }}</el-tag>
          </template>
          <el-descriptions :column="2" border size="small">
            <el-descriptions-item label="行覆盖率">{{ detail.line_rate }}%</el-descriptions-item>
            <el-descriptions-item label="分支覆盖率">{{ detail.branch_rate }}%</el-descriptions-item>
            <el-descriptions-item label="覆盖行数">{{ detail.covered_lines }}/{{ detail.total_lines }}</el-descriptions-item>
            <el-descriptions-item label="覆盖分支">{{ detail.covered_branches }}/{{ detail.total_branches }}</el-descriptions-item>
          </el-descriptions>

          <el-divider>文件级明细</el-divider>
          <el-table :data="detail.files" size="small" border max-height="460" empty-text="无文件明细">
            <el-table-column prop="path" label="文件" show-overflow-tooltip />
            <el-table-column label="行覆盖" width="90" align="center">
              <template #default="{ row }">
                <span :class="rateClass(row.line_rate)">{{ fmt(row.line_rate) }}%</span>
              </template>
            </el-table-column>
            <el-table-column prop="covered_lines" label="行(覆盖/总)" width="110" align="center">
              <template #default="{ row }">{{ row.covered_lines }}/{{ row.total_lines }}</template>
            </el-table-column>
          </el-table>
        </el-card>
        <el-card shadow="hover" v-else>
          <el-empty description="选择左侧报告查看明细" />
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage, type UploadFile } from 'element-plus'
import { coverageApi, projectApi } from '@/api'

const projects = ref<any[]>([])
const projectId = ref<string>('')
const tool = ref<string>('coverage.py')
const language = ref<string>('')
const testRunId = ref<string>('')
const selectedFile = ref<File | null>(null)
const uploading = ref(false)

const reports = ref<any[]>([])
const loading = ref(false)
const detail = ref<any>(null)

function rateType(rate: number): any {
  const r = Number(rate)
  if (r >= 80) return 'success'
  if (r >= 60) return 'warning'
  return 'danger'
}
function rateClass(rate: any): string {
  const r = Number(rate)
  if (r >= 80) return 'rate-good'
  if (r >= 60) return 'rate-mid'
  return 'rate-bad'
}
function fmt(v: any): string {
  return v == null ? '-' : Number(v).toFixed(1)
}

function onFileChange(file: UploadFile) {
  const raw = (file.raw as File) || (file as any)
  selectedFile.value = raw
}
function clearFile() {
  selectedFile.value = null
}

async function uploadReport() {
  if (!projectId.value || !tool.value || !selectedFile.value) return
  uploading.value = true
  try {
    const res: any = await coverageApi.upload(selectedFile.value, {
      project_id: projectId.value,
      tool: tool.value,
      language: language.value || undefined,
      test_run_id: testRunId.value || undefined,
    })
    const d = res?.data || {}
    ElMessage.success(
      `已入库：行覆盖 ${d.line_rate}% / 分支 ${d.branch_rate}%（${d.file_count} 个文件）`
    )
    await loadReports()
  } catch (e: any) {
    /* 拦截器已提示 */
  } finally {
    uploading.value = false
  }
}

async function loadReports() {
  if (!projectId.value) return
  loading.value = true
  try {
    const res: any = await coverageApi.list({ project_id: projectId.value })
    reports.value = res?.data || []
  } catch {
    reports.value = []
  } finally {
    loading.value = false
  }
}
async function viewReport(row: any) {
  try {
    const res: any = await coverageApi.get(row.id)
    detail.value = res?.data || null
  } catch {
    detail.value = null
  }
}
async function removeReport(row: any) {
  try {
    await coverageApi.remove(row.id)
    ElMessage.success('已删除')
    if (detail.value?.id === row.id) detail.value = null
    await loadReports()
  } catch {
    /* ignore */
  }
}

async function loadProjects() {
  try {
    const res: any = await projectApi.getList()
    const d = res?.data ?? res
    projects.value = Array.isArray(d) ? d : d?.list || d?.items || []
    if (!projects.value.length) {
      ElMessage.warning('未获取到项目列表，请先在「数据源管理 / 项目」中创建项目后再上传覆盖率')
    }
  } catch (e: any) {
    projects.value = []
    ElMessage.error('加载项目列表失败：' + (e?.message || e?.response?.data?.detail || '请检查后端 /api/projects 是否可用'))
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
.el-upload__tip code {
  background: #f0f2f5;
  padding: 1px 4px;
  border-radius: 3px;
}
.rate-good {
  color: #67c23a;
  font-weight: 600;
}
.rate-mid {
  color: #e6a23c;
  font-weight: 600;
}
.rate-bad {
  color: #f56c6c;
  font-weight: 600;
}
</style>
