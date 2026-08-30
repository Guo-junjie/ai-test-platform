<template>
  <div class="source-manage-page">
    <el-card shadow="hover">
      <template #header>
        <div class="card-header">
          <span>数据源管理</span>
          <el-button
            v-if="activeTab !== 'upload'"
            type="primary"
            @click="openForm"
          >
            <el-icon><Plus /></el-icon>
            添加数据源
          </el-button>
        </div>
      </template>

      <el-tabs v-model="activeTab" @tab-change="handleTabChange">
        <!-- ==================== GitHub Tab ==================== -->
        <el-tab-pane label="GitHub 仓库" name="github">
          <el-table
            :data="githubSources"
            v-loading="loading"
            stripe
            style="width: 100%"
          >
            <el-table-column prop="name" label="仓库名称" min-width="140" />
            <el-table-column label="仓库 URL" min-width="280">
              <template #default="{ row }">
                <span class="mono-text">{{ row.config?.repo_url || '-' }}</span>
              </template>
            </el-table-column>
            <el-table-column label="分支" width="100">
              <template #default="{ row }">
                <el-tag size="small">{{ row.config?.branch || 'main' }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="is_active" label="状态" width="80">
              <template #default="{ row }">
                <el-tag :type="row.is_active ? 'success' : 'info'" size="small">
                  {{ row.is_active ? '活跃' : '已停用' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="280" fixed="right">
              <template #default="{ row }">
                <el-button
                  size="small"
                  @click="handleEdit(row)"
                >
                  编辑
                </el-button>
                <el-button
                  size="small"
                  type="primary"
                  :loading="fetchingId === row.id"
                  @click="handleFetch(row)"
                >
                  拉取代码
                </el-button>
                <el-button
                  size="small"
                  type="danger"
                  @click="handleDisconnect(row)"
                >
                  断开
                </el-button>
              </template>
            </el-table-column>
          </el-table>
          <el-empty
            v-if="!loading && githubSources.length === 0"
            description="暂无已连接的 GitHub 仓库"
          />
        </el-tab-pane>

        <!-- ==================== SVN Tab ==================== -->
        <el-tab-pane label="SVN 仓库" name="svn">
          <el-table
            :data="svnSources"
            v-loading="loading"
            stripe
            style="width: 100%"
          >
            <el-table-column prop="name" label="仓库名称" min-width="140" />
            <el-table-column label="SVN URL" min-width="280">
              <template #default="{ row }">
                <span class="mono-text">{{ row.config?.svn_url || '-' }}</span>
              </template>
            </el-table-column>
            <el-table-column label="用户名" width="120">
              <template #default="{ row }">
                {{ row.config?.svn_username || '-' }}
              </template>
            </el-table-column>
            <el-table-column prop="is_active" label="状态" width="80">
              <template #default="{ row }">
                <el-tag :type="row.is_active ? 'success' : 'info'" size="small">
                  {{ row.is_active ? '活跃' : '已停用' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="280" fixed="right">
              <template #default="{ row }">
                <el-button
                  size="small"
                  @click="handleEdit(row)"
                >
                  编辑
                </el-button>
                <el-button
                  size="small"
                  type="primary"
                  :loading="fetchingId === row.id"
                  @click="handleFetch(row)"
                >
                  拉取代码
                </el-button>
                <el-button
                  size="small"
                  type="danger"
                  @click="handleDisconnect(row)"
                >
                  断开
                </el-button>
              </template>
            </el-table-column>
          </el-table>
          <el-empty
            v-if="!loading && svnSources.length === 0"
            description="暂无已连接的 SVN 仓库"
          />
        </el-tab-pane>

        <!-- ==================== Upload Tab ==================== -->
        <el-tab-pane label="上传文件" name="upload">
          <el-upload
            class="upload-area"
            drag
            :auto-upload="true"
            :show-file-list="false"
            :http-request="handleUpload"
            accept=".zip,.tar.gz,.tgz,.tar"
          >
            <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
            <div class="el-upload__text">
              拖拽文件到此处，或<em>点击上传</em>
            </div>
            <template #tip>
              <div class="el-upload__tip">
                支持 .zip / .tar.gz / .tgz / .tar 格式，最大 500MB
              </div>
            </template>
          </el-upload>

          <!-- 上传结果 -->
          <el-descriptions
            v-if="uploadResult"
            title="上传结果"
            :column="1"
            border
            class="upload-result"
          >
            <el-descriptions-item label="状态">
              <el-tag type="success">已接收</el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="本地路径">
              <span class="mono-text">{{ uploadResult.local_path }}</span>
            </el-descriptions-item>
            <el-descriptions-item label="快照 ID">
              <span class="mono-text">{{ uploadResult.snapshot_id || '-' }}</span>
            </el-descriptions-item>
            <el-descriptions-item label="文件总数">
              {{ uploadResult.total_files }}
            </el-descriptions-item>
          </el-descriptions>
        </el-tab-pane>
      </el-tabs>
    </el-card>

    <!-- 数据源表单弹窗 -->
    <SourceForm
      :source-type="activeTab === 'svn' ? 'svn' : 'github'"
      :visible="formVisible"
      :editing-source="editingSource"
      @save="handleFormSave"
      @cancel="handleFormCancel"
    />

    <!-- 拉取结果弹窗 -->
    <el-dialog
      v-model="fetchResultVisible"
      title="代码拉取结果"
      width="560px"
    >
      <el-descriptions v-if="fetchResult" :column="1" border>
        <el-descriptions-item label="本地路径">
          <span class="mono-text">{{ fetchResult.local_path }}</span>
        </el-descriptions-item>
        <el-descriptions-item label="版本 ID">
          <span class="mono-text">{{ fetchResult.version_id }}</span>
        </el-descriptions-item>
        <el-descriptions-item label="版本描述">
          {{ fetchResult.version_label }}
        </el-descriptions-item>
        <el-descriptions-item label="快照 ID">
          <span class="mono-text">{{ fetchResult.snapshot_id || '-' }}</span>
        </el-descriptions-item>
        <el-descriptions-item label="变更文件数">
          {{ fetchResult.files_changed?.length || 0 }}
        </el-descriptions-item>
        <el-descriptions-item label="总文件数">
          {{ fetchResult.total_files }}
        </el-descriptions-item>
        <el-descriptions-item label="数据源类型">
          {{ fetchResult.source_type }}
        </el-descriptions-item>
      </el-descriptions>
      <template #footer>
        <el-button type="primary" @click="fetchResultVisible = false">
          关闭
        </el-button>
      </template>
    </el-dialog>

    <!-- CI/CD 集成 -->
    <el-card shadow="hover" style="margin-top: 16px">
      <template #header>
        <div class="card-header">
          <span>CI/CD 集成（Jenkins / GitLab CI / GitHub Actions）</span>
        </div>
      </template>

      <el-form label-width="130px" style="max-width: 720px">
        <el-form-item label="项目">
          <el-select v-model="ciProjectId" placeholder="选择项目" style="width: 100%" @change="loadCIConfig">
            <el-option v-for="p in ciProjects" :key="p.id" :label="p.name" :value="p.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="CI Token">
          <div style="display:flex; gap:8px; width:100%">
            <el-input v-model="ciToken" readonly placeholder="未生成（生成后仅显示一次，请妥善保存）" />
            <el-button :disabled="!ciProjectId || !canManageCI" :loading="tokenLoading" @click="handleRotateToken">
              {{ ciToken ? '轮换' : '生成' }}
            </el-button>
          </div>
        </el-form-item>
        <el-form-item label="测试完成回调">
          <el-input v-model="ciCallbackUrl" placeholder="https://ci.example.com/webhook（测试完成后 POST 结果摘要，可空）" />
        </el-form-item>
        <el-form-item label="push 自动测试">
          <div style="display:flex; align-items:center; gap:12px; width:100%">
            <el-switch v-model="ciTriggerEnabled" />
            <el-input
              v-model="ciTriggerBranches"
              placeholder="触发分支，逗号分隔（留空 = 全部分支），如 main,release"
              style="flex:1"
              :disabled="!ciTriggerEnabled"
            />
          </div>
        </el-form-item>
        <el-form-item label="质量徽章">
          <div style="display:flex; align-items:center; gap:8px">
            <img v-if="ciProjectId" :src="badgeSrc" alt="badge" style="height:20px" />
            <el-button size="small" :disabled="!ciProjectId" @click="copyBadgeUrl">复制 Markdown</el-button>
          </div>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :disabled="!ciProjectId || !canManageCI" :loading="ciSaving" @click="saveCIConfig">
            保存 CI 配置
          </el-button>
        </el-form-item>
      </el-form>

      <el-alert type="info" :closable="false" show-icon title="CI 用法" description="
curl -X POST 平台地址/api/webhook/trigger -H 'X-CI-Token: <Token>' -d '{&quot;branch&quot;:&quot;main&quot;}'
# 轮询卡点：curl 平台地址/api/webhook/ci-result/<test_run_id>?token=<Token> → ci_passed" />
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { UploadRequestOptions } from 'element-plus'
import { sourceApi, uploadApi, projectApi, projectConfigApi } from '@/api'
import { useAuthStore } from '@/stores'
import SourceForm from '@/components/SourceForm.vue'

// ==================== State ====================

const activeTab = ref<'github' | 'svn' | 'upload'>('github')
const loading = ref(false)
const fetchingId = ref<string | null>(null)
const uploading = ref(false)
const formVisible = ref(false)
/** 编辑模式：传入要编辑的 source 行；null = 添加模式 */
const editingSource = ref<any | null>(null)
const fetchResultVisible = ref(false)

const allSources = ref<any[]>([])
const uploadResult = ref<any>(null)
const fetchResult = ref<any>(null)

// ==================== Computed ====================

const githubSources = computed(() =>
  allSources.value.filter((s) => s.source_type === 'github')
)

const svnSources = computed(() =>
  allSources.value.filter((s) => s.source_type === 'svn')
)

// ==================== Methods ====================

async function loadSources() {
  loading.value = true
  try {
    const res: any = await sourceApi.list()
    allSources.value = res?.data?.list || []
  } catch {
    allSources.value = []
  } finally {
    loading.value = false
  }
}

function handleTabChange() {
  // Tab 切换时不需要额外加载
}

function openForm() {
  editingSource.value = null  // 添加模式
  formVisible.value = true
}

function handleEdit(row: any) {
  editingSource.value = row   // 编辑模式，把整行传给表单
  formVisible.value = true
}

function handleFormSave() {
  formVisible.value = false
  editingSource.value = null
  loadSources()
}

function handleFormCancel() {
  formVisible.value = false
  editingSource.value = null
}

async function handleFetch(row: any) {
  fetchingId.value = row.id
  try {
    const fetchConfig: Record<string, any> = {
      // 仅传 source_id，由后端从数据库读取已加密配置并解密出真实凭据，
      // 避免把列表里脱敏后的 token 当作真 token 发回去导致 clone 失败。
      source_id: row.id,
      source_type: row.source_type,
      incremental: true,
    }

    const res: any = await sourceApi.fetch(fetchConfig)
    fetchResult.value = res?.data || null
    fetchResultVisible.value = true
    ElMessage.success('代码拉取成功')
  } catch {
    // 错误已由 axios 拦截器处理
  } finally {
    fetchingId.value = null
  }
}

async function handleDisconnect(row: any) {
  try {
    await ElMessageBox.confirm(
      `确定要断开数据源「${row.name}」吗？`,
      '确认断开',
      { type: 'warning' }
    )
    await sourceApi.disconnect(row.id)
    ElMessage.success('数据源已断开')
    loadSources()
  } catch {
    // 用户取消
  }
}

async function handleUpload(options: UploadRequestOptions) {
  uploading.value = true
  try {
    const res: any = await uploadApi.upload(options.file as File)
    uploadResult.value = res?.data || null
    ElMessage.success('文件上传并处理成功')
  } catch {
    // 错误已由 axios 拦截器处理
  } finally {
    uploading.value = false
  }
}

// ==================== Lifecycle ====================

onMounted(() => {
  loadSources()
})

// ============ CI/CD 集成 ============
const authStoreCI = useAuthStore()
const canManageCI = computed(() => ['super_admin', 'admin'].includes(authStoreCI.role))
const ciProjects = ref<any[]>([])
const ciProjectId = ref<string>('')
const ciToken = ref<string>('')
const ciCallbackUrl = ref<string>('')
const ciTriggerEnabled = ref<boolean>(false)
const ciTriggerBranches = ref<string>('')
const tokenLoading = ref<boolean>(false)
const ciSaving = ref<boolean>(false)
const badgeSrc = computed(() =>
  ciProjectId.value ? projectConfigApi.badgeUrl(ciProjectId.value) : ''
)

async function loadCIProjects(): Promise<void> {
  try {
    const res: any = await projectApi.getList()
    ciProjects.value = res?.data ?? []
  } catch {
    ciProjects.value = []
  }
}

async function loadCIConfig(): Promise<void> {
  ciToken.value = ''
  if (!ciProjectId.value) return
  try {
    const res: any = await projectConfigApi.getCIConfig(ciProjectId.value)
    if (res?.code === 0 && res?.data) {
      ciCallbackUrl.value = res.data.callback_url || ''
      ciTriggerEnabled.value = !!res.data.auto_trigger?.enabled
      ciTriggerBranches.value = (res.data.auto_trigger?.branches || []).join(',')
    }
  } catch { /* 忽略 */ }
}

async function handleRotateToken(): Promise<void> {
  try {
    tokenLoading.value = true
    const res: any = await projectConfigApi.rotateCIToken(ciProjectId.value)
    if (res?.code === 0) {
      ciToken.value = res.data.token
      ElMessage.success('Token 已生成，请立即保存（仅本次可见）')
    } else {
      ElMessage.error(res?.message || '生成失败')
    }
  } finally {
    tokenLoading.value = false
  }
}

async function saveCIConfig(): Promise<void> {
  try {
    ciSaving.value = true
    const res: any = await projectConfigApi.updateCIConfig(ciProjectId.value, {
      callback_url: ciCallbackUrl.value.trim() || undefined,
      auto_trigger_enabled: ciTriggerEnabled.value,
      auto_trigger_branches: ciTriggerBranches.value
        .split(',')
        .map((b) => b.trim())
        .filter(Boolean),
    })
    if (res?.code === 0) {
      ElMessage.success('CI 配置已保存')
    } else {
      ElMessage.error(res?.message || '保存失败')
    }
  } finally {
    ciSaving.value = false
  }
}

async function copyBadgeUrl(): Promise<void> {
  const origin = window.location.origin
  const md = `[![tests](${origin}${projectConfigApi.badgeUrl(ciProjectId.value)})](${origin}/coverage)`
  try {
    await navigator.clipboard.writeText(md)
    ElMessage.success('Markdown 已复制')
  } catch {
    ElMessage.warning(md)
  }
}

onMounted(() => {
  void loadCIProjects()
})
</script>

<style scoped>
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.mono-text {
  font-family: 'Courier New', Consolas, monospace;
  font-size: 13px;
  color: #606266;
  word-break: break-all;
}

.upload-area {
  width: 100%;
  margin-bottom: 20px;
}

.upload-result {
  margin-top: 20px;
}
</style>
