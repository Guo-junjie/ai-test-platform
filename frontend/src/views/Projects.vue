<template>
  <div class="projects-page">
    <el-card shadow="hover">
      <template #header>
        <div class="card-header">
          <span>项目管理</span>
          <el-button type="primary" @click="openCreate">
            <el-icon><Plus /></el-icon>
            新建项目
          </el-button>
        </div>
      </template>

      <el-table :data="projects" v-loading="loading" stripe @row-click="openDetail">
        <el-table-column prop="name" label="项目名称" min-width="180" show-overflow-tooltip />
        <el-table-column prop="description" label="描述" min-width="220" show-overflow-tooltip>
          <template #default="{ row }">{{ row.description || '—' }}</template>
        </el-table-column>
        <el-table-column label="代码来源" width="110" align="center">
          <template #default="{ row }">
            <el-tag size="small" effect="plain">{{ sourceLabel(row.source_type) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="创建时间" width="170">
          <template #default="{ row }">
            <span class="time-text">{{ formatTime(row.created_at) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="140" fixed="right">
          <template #default="{ row }">
            <el-button size="small" type="primary" plain @click.stop="openDetail(row)">详情</el-button>
          </template>
        </el-table-column>
      </el-table>

      <el-empty v-if="!loading && projects.length === 0" description="还没有项目 —— 点击右上角「新建项目」开始">
        <el-button type="primary" @click="openCreate">新建第一个项目</el-button>
      </el-empty>
    </el-card>

    <!-- 新建项目 -->
    <el-dialog v-model="createVisible" title="新建项目" width="560px" :close-on-click-modal="false">
      <el-form label-width="90px">
        <el-form-item label="名称" required>
          <el-input v-model="createForm.name" placeholder="例如：订单中心" maxlength="200" show-word-limit />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="createForm.description" type="textarea" :rows="2" placeholder="项目说明（可选）" />
        </el-form-item>
        <el-form-item label="代码来源">
          <el-radio-group v-model="createForm.source_type">
            <el-radio-button value="github">GitHub</el-radio-button>
            <el-radio-button value="svn">SVN</el-radio-button>
            <el-radio-button value="upload">本地上传</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <template v-if="createForm.source_type === 'github'">
          <el-form-item label="仓库 URL">
            <el-input v-model="createForm.repo_url" placeholder="https://github.com/owner/repo（可留空，之后配置）" />
          </el-form-item>
          <el-form-item label="Token">
            <el-input v-model="createForm.github_token" type="password" show-password placeholder="私有仓库需要（可留空）" />
          </el-form-item>
          <el-form-item label="分支">
            <el-input v-model="createForm.branch" placeholder="main" />
          </el-form-item>
        </template>
        <template v-if="createForm.source_type === 'svn'">
          <el-form-item label="SVN URL">
            <el-input v-model="createForm.svn_url" placeholder="https://svn.example.com/svn/project" />
          </el-form-item>
          <el-form-item label="用户名">
            <el-input v-model="createForm.svn_username" />
          </el-form-item>
          <el-form-item label="密码">
            <el-input v-model="createForm.svn_password" type="password" show-password />
          </el-form-item>
        </template>
        <template v-if="createForm.source_type === 'upload'">
          <el-form-item label="代码包">
            <el-upload
              drag
              :auto-upload="false"
              :file-list="createFileList"
              :on-change="onCreateFileChange"
              accept=".zip,.tar.gz,.tgz,.tar"
              style="width: 100%"
            >
              <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
              <div class="el-upload__text">拖拽文件到此处，或<em>点击选择</em></div>
              <template #tip>
                <div class="el-upload__tip">
                  支持 ZIP / TAR.GZ / TAR；创建项目后立即上传为第一个代码版本（可跳过，稍后在项目详情上传）
                </div>
              </template>
            </el-upload>
          </el-form-item>
        </template>
        <el-alert
          type="info"
          :closable="false"
          show-icon
          title="创建后进入项目详情：可继续上传代码或从仓库拉取，形成项目代码版本；测试任务将引用这些版本执行"
        />
      </el-form>
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="submitCreate">创建</el-button>
      </template>
    </el-dialog>

    <!-- 项目详情抽屉 -->
    <el-drawer v-model="detailVisible" :title="`项目详情 - ${current?.name || ''}`" size="640px">
      <div v-if="current" class="detail-body">
        <el-descriptions :column="1" border size="small">
          <el-descriptions-item label="项目 ID">
            <span class="mono-text">{{ current.id }}</span>
          </el-descriptions-item>
          <el-descriptions-item label="描述">{{ current.description || '—' }}</el-descriptions-item>
          <el-descriptions-item label="代码来源">{{ sourceLabel(current.source_type) }}</el-descriptions-item>
        </el-descriptions>

        <div class="section-header">
          <span>代码版本</span>
          <div>
            <el-upload
              :show-file-list="false"
              :http-request="handleUpload"
              accept=".zip,.tar.gz,.tgz,.tar"
              style="display: inline-block; margin-right: 8px"
            >
              <el-button size="small" type="primary" plain :loading="uploading">
                <el-icon><UploadFilled /></el-icon>
                上传代码
              </el-button>
            </el-upload>
            <el-button size="small" plain :loading="fetching" @click="fetchFromRepo">
              <el-icon><Refresh /></el-icon>
              从仓库拉取
            </el-button>
          </div>
        </div>

        <el-table :data="versions" v-loading="versionsLoading" stripe size="small">
          <el-table-column label="版本" min-width="130" show-overflow-tooltip>
            <template #default="{ row }">
              <span class="mono-text">{{ row.version_id?.substring(0, 12) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="来源" width="80" align="center">
            <template #default="{ row }">
              <el-tag size="small" effect="plain">{{ sourceLabel(row.source_type) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="文件数" width="80" align="center">
            <template #default="{ row }">{{ row.total_files ?? '—' }}</template>
          </el-table-column>
          <el-table-column label="说明" min-width="140" show-overflow-tooltip>
            <template #default="{ row }">{{ row.note || row.branch || '—' }}</template>
          </el-table-column>
          <el-table-column label="时间" width="150">
            <template #default="{ row }">
              <span class="time-text">{{ formatTime(row.created_at) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="110" fixed="right">
            <template #default="{ row }">
              <el-button
                size="small"
                type="success"
                plain
                :disabled="executing"
                @click="runOnVersion(row)"
              >
                执行测试
              </el-button>
            </template>
          </el-table-column>
        </el-table>
        <el-empty
          v-if="!versionsLoading && versions.length === 0"
          description="还没有代码版本 —— 上传压缩包或从仓库拉取"
          :image-size="80"
        />
      </div>
    </el-drawer>
  </div>
</template>

<script lang="ts">
/**
 * Projects.vue —— 项目管理（R1）
 *
 * 核心链路第一步：新建项目 → 项目下接入代码（上传/拉取 → 代码版本）
 * → 测试任务引用版本执行。代码是项目的属性，不再随任务走。
 *
 * 实现注意：Options API（vue-tsc 4.x 对大块 script setup 有已知 bug）。
 */
import { defineComponent } from 'vue'
import { Plus, UploadFilled, Refresh } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import type { UploadRequestOptions } from 'element-plus'
import { projectApi, projectCodeApi, testRunApi } from '@/api'

const SOURCE_LABELS: Record<string, string> = {
  github: 'GitHub',
  svn: 'SVN',
  upload: '本地上传',
}

export default defineComponent({
  name: 'ProjectsView',
  components: { Plus, UploadFilled, Refresh },
  data() {
    return {
      loading: false,
      projects: [] as any[],

      createVisible: false,
      creating: false,
      createForm: {
        name: '',
        description: '',
        source_type: 'github',
        repo_url: '',
        github_token: '',
        branch: 'main',
        svn_url: '',
        svn_username: '',
        svn_password: '',
      },
      // 「本地上传」模式下随项目一起上传的代码包（创建成功后立即登记为版本）
      createUploadFile: null as File | null,
      createFileList: [] as any[],

      detailVisible: false,
      current: null as any,
      versions: [] as any[],
      versionsLoading: false,
      uploading: false,
      fetching: false,
      executing: false,
    }
  },
  methods: {
    sourceLabel(t?: string): string {
      return SOURCE_LABELS[t || ''] || t || '—'
    },
    formatTime(time?: string): string {
      if (!time) return '—'
      try {
        return new Date(time).toLocaleString('zh-CN')
      } catch {
        return time
      }
    },
    resetCreateForm(): void {
      this.createForm = {
        name: '',
        description: '',
        source_type: 'github',
        repo_url: '',
        github_token: '',
        branch: 'main',
        svn_url: '',
        svn_username: '',
        svn_password: '',
      }
      this.createUploadFile = null
      this.createFileList = []
    },
    onCreateFileChange(uploadFile: any): void {
      const f: File | undefined = uploadFile?.raw
      if (!f) return
      const name = (f.name || '').toLowerCase()
      const ok = name.endsWith('.zip') || name.endsWith('.tar.gz') || name.endsWith('.tgz') || name.endsWith('.tar')
      if (!ok) {
        ElMessage.warning('仅支持 ZIP / TAR.GZ / TAR 格式')
        this.createUploadFile = null
        this.createFileList = []
        return
      }
      this.createUploadFile = f
      this.createFileList = [uploadFile]
    },
    async loadProjects(): Promise<void> {
      this.loading = true
      try {
        const res: any = await projectApi.getList()
        const d = res?.data ?? res
        this.projects = Array.isArray(d) ? d : d?.list || d?.items || []
      } catch {
        this.projects = []
      } finally {
        this.loading = false
      }
    },
    openCreate(): void {
      this.resetCreateForm()
      this.createVisible = true
    },
    async submitCreate(): Promise<void> {
      const name = this.createForm.name.trim()
      if (name.length < 1) {
        ElMessage.warning('请输入项目名称')
        return
      }
      this.creating = true
      try {
        const payload: any = {
          name,
          description: this.createForm.description.trim() || undefined,
          source_type: this.createForm.source_type,
        }
        // 仓库配置随项目一起写入 source_config（后续「从仓库拉取」直接用）
        if (this.createForm.source_type === 'github' && this.createForm.repo_url) {
          payload.source_config = {
            repo_url: this.createForm.repo_url,
            github_token: this.createForm.github_token || '',
            branch: this.createForm.branch || 'main',
          }
        } else if (this.createForm.source_type === 'svn' && this.createForm.svn_url) {
          payload.source_config = {
            svn_url: this.createForm.svn_url,
            svn_username: this.createForm.svn_username || '',
            svn_password: this.createForm.svn_password || '',
          }
        }
        const res: any = await projectApi.create(payload)
        const newId = res?.data?.id
        ElMessage.success(`项目「${name}」创建成功`)

        // 「本地上传」模式且选择了代码包：立即登记为第一个代码版本
        if (newId && this.createForm.source_type === 'upload' && this.createUploadFile) {
          try {
            await projectCodeApi.upload(newId, this.createUploadFile)
            ElMessage.success('代码包已上传为项目的第一个代码版本')
          } catch {
            /* 拦截器已提示；项目已创建，可稍后在详情里重传 */
          }
        }

        this.createVisible = false
        await this.loadProjects()
        const created = this.projects.find((p: any) => p.id === newId)
        if (created) this.openDetail(created)
      } catch {
        /* 拦截器已提示（如重名 409 / 无权限 403） */
      } finally {
        this.creating = false
      }
    },
    async openDetail(row: any): Promise<void> {
      this.current = row
      this.detailVisible = true
      this.loadVersions()
    },
    async loadVersions(): Promise<void> {
      if (!this.current) return
      this.versionsLoading = true
      try {
        const res: any = await projectCodeApi.listVersions(this.current.id)
        this.versions = res?.data?.list || []
      } catch {
        this.versions = []
      } finally {
        this.versionsLoading = false
      }
    },
    async handleUpload(options: UploadRequestOptions): Promise<void> {
      if (!this.current) return
      this.uploading = true
      try {
        await projectCodeApi.upload(this.current.id, options.file as File)
        ElMessage.success('代码已上传并登记为项目版本')
        this.loadVersions()
      } catch {
        /* 拦截器已提示 */
      } finally {
        this.uploading = false
      }
    },
    async fetchFromRepo(): Promise<void> {
      if (!this.current) return
      this.fetching = true
      try {
        await projectCodeApi.fetch(this.current.id)
        ElMessage.success('代码已从仓库拉取并登记为项目版本')
        this.loadVersions()
      } catch {
        /* 拦截器已提示 */
      } finally {
        this.fetching = false
      }
    },
    async runOnVersion(row: any): Promise<void> {
      if (!this.current) return
      this.executing = true
      try {
        await testRunApi.create({
          mode: 'auto',
          source_type: row.source_type || 'upload',
          project_id: this.current.id,
          code_version_id: row.id,
        })
        ElMessage.success('测试任务已启动（引用该代码版本），可在「测试任务」页查看进度')
        this.detailVisible = false
      } catch {
        /* 拦截器已提示 */
      } finally {
        this.executing = false
      }
    },
  },
  mounted() {
    this.loadProjects()
  },
})
</script>

<style scoped>
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.time-text {
  font-size: 12px;
  color: #606266;
}
.mono-text {
  font-family: 'Courier New', Consolas, monospace;
  font-size: 13px;
  color: #606266;
  word-break: break-all;
}
.detail-body {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 8px;
  font-weight: 600;
  color: #303133;
}
</style>
