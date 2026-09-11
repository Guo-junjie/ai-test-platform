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
        <el-form-item label="被测服务 URL">
          <el-input
            v-model="createForm.target_service_url"
            placeholder="http://192.168.1.100:8080（真实被测服务地址，选填）"
          >
            <template #append>
              <el-button :loading="probing" @click="handleProbeUrl(createForm.target_service_url)">连通测试</el-button>
            </template>
          </el-input>
        </el-form-item>
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
          <el-descriptions-item label="代码来源">
            <span>{{ sourceLabel(current.source_type) }}</span>
            <el-button size="small" text type="primary" style="margin-left: 8px" @click="openEditSource">修改</el-button>
          </el-descriptions-item>
          <el-descriptions-item label="仓库配置">
            <el-link type="primary" :underline="false" @click="$router.push('/sources')">在仓库配置中维护</el-link>
          </el-descriptions-item>
          <el-descriptions-item label="被测服务 URL">
            <div style="display: flex; align-items: center; justify-content: space-between">
              <span class="mono-text" style="color: var(--el-color-primary)">
                {{ current.target_service_url || (current.source_config && current.source_config.target_service_url) || '未配置（将尝试本地 Docker 构建）' }}
              </span>
              <div v-if="current.target_service_url || (current.source_config && current.source_config.target_service_url)">
                <el-button size="small" type="primary" plain :loading="probing" @click="handleProbeUrl(current.target_service_url || current.source_config.target_service_url)">连通测试</el-button>
              </div>
            </div>
          </el-descriptions-item>
          <el-descriptions-item label="覆盖率探针">
            <div style="display: flex; align-items: center; justify-content: space-between">
              <span class="mono-text">
                {{ formatCoverageInfo(current) }}
              </span>
              <el-button size="small" type="success" plain @click="$router.push(`/coverage?project_id=${current.id}`)">
                看板 / 探针配置
              </el-button>
            </div>
          </el-descriptions-item>
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

        <!-- M1：测试环境档案 -->
        <div class="section-header">
          <span>测试环境</span>
          <el-button size="small" type="primary" plain @click="openEnvDialog()">新建环境</el-button>
        </div>
        <el-table :data="environments" v-loading="envsLoading" stripe size="small">
          <el-table-column prop="name" label="名称" min-width="120" show-overflow-tooltip />
          <el-table-column label="地址" min-width="160" show-overflow-tooltip>
            <template #default="{ row }">
              <span class="mono-text">{{ row.base_url || '—' }}</span>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="90" align="center">
            <template #default="{ row }">
              <el-tag size="small" :type="row.status === 'published' ? 'success' : 'info'">
                {{ row.status === 'published' ? '已发布' : '草稿' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="健康" width="80" align="center">
            <template #default="{ row }">
              <el-tag v-if="row.health_status === 'healthy'" size="small" type="success">正常</el-tag>
              <el-tag v-else-if="row.health_status" size="small" type="warning">异常</el-tag>
              <span v-else>—</span>
            </template>
          </el-table-column>
          <el-table-column label="修订" width="70" align="center">
            <template #default="{ row }">{{ row.revision ? `r${row.revision}` : '—' }}</template>
          </el-table-column>
          <el-table-column label="操作" width="210" fixed="right">
            <template #default="{ row }">
              <el-button size="small" plain @click="openEnvDialog(row)">编辑</el-button>
              <el-button size="small" plain :loading="row._checking" @click="checkEnv(row)">检查</el-button>
              <el-button size="small" type="success" plain :loading="row._publishing" @click="publishEnv(row)">
                {{ row.status === 'published' ? '重新发布' : '发布' }}
              </el-button>
            </template>
          </el-table-column>
        </el-table>
        <div class="env-tip">
          执行测试计划时必须选择「已发布」环境；发布时固化配置为不可变修订版（含健康检查结果），保证历史运行可复现。
        </div>
      </div>
    </el-drawer>

    <!-- 新建/编辑环境对话框 -->
    <el-dialog v-model="envDialogVisible" :title="envForm.id ? '编辑环境' : '新建环境'" width="560px" :close-on-click-modal="false">
      <el-form label-width="100px">
        <el-form-item label="名称" required>
          <el-input v-model="envForm.name" placeholder="例如：测试环境 / 预发环境" maxlength="200" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="envForm.description" type="textarea" :rows="2" placeholder="用途说明（可选）" />
        </el-form-item>
        <el-form-item label="被测地址" required>
          <el-input v-model="envForm.base_url" placeholder="http://host:port" />
        </el-form-item>
        <el-form-item label="健康检查路径">
          <el-input v-model="envForm.healthcheck_path" placeholder="/health（可选，发布时自动检查）" />
        </el-form-item>
        <el-form-item label="认证方式">
          <el-radio-group v-model="envForm.auth_strategy">
            <el-radio-button value="none">无</el-radio-button>
            <el-radio-button value="bearer">Bearer</el-radio-button>
            <el-radio-button value="basic">Basic</el-radio-button>
            <el-radio-button value="apikey">ApiKey</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item v-if="envForm.auth_strategy !== 'none'" label="凭据">
          <el-input v-model="envForm.auth_token" type="password" show-password placeholder="留空保持原有凭据" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="envDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="envSaving" @click="submitEnv">保存</el-button>
      </template>
    </el-dialog>

    <!-- 修改代码来源对话框 -->
    <el-dialog v-model="editSourceVisible" title="修改代码来源" width="560px" :close-on-click-modal="false">
      <el-form label-width="90px">
        <el-form-item label="代码来源">
          <el-radio-group v-model="editForm.source_type">
            <el-radio-button value="github">GitHub</el-radio-button>
            <el-radio-button value="svn">SVN</el-radio-button>
            <el-radio-button value="upload">本地上传</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <template v-if="editForm.source_type === 'github'">
          <el-form-item label="仓库 URL">
            <el-input v-model="editForm.repo_url" placeholder="https://github.com/owner/repo" />
          </el-form-item>
          <el-form-item label="Token">
            <el-input v-model="editForm.github_token" type="password" show-password placeholder="留空保持原有 Token" />
          </el-form-item>
          <el-form-item label="分支">
            <el-input v-model="editForm.branch" placeholder="main" />
          </el-form-item>
        </template>
        <template v-if="editForm.source_type === 'svn'">
          <el-form-item label="SVN URL">
            <el-input v-model="editForm.svn_url" placeholder="https://svn.example.com/svn/project" />
          </el-form-item>
          <el-form-item label="用户名">
            <el-input v-model="editForm.svn_username" />
          </el-form-item>
          <el-form-item label="密码">
            <el-input v-model="editForm.svn_password" type="password" show-password placeholder="留空保持原有密码" />
          </el-form-item>
        </template>
        <template v-if="editForm.source_type === 'upload'">
          <el-alert
            type="info"
            :closable="false"
            show-icon
            title="本地上传模式无需仓库配置，代码通过详情页「上传代码」按钮进入项目"
          />
        </template>
        <el-form-item label="被测服务 URL">
          <el-input
            v-model="editForm.target_service_url"
            placeholder="http://192.168.1.100:8080（真实环境地址）"
          >
            <template #append>
              <el-button :loading="probing" @click="handleProbeUrl(editForm.target_service_url)">连通测试</el-button>
            </template>
          </el-input>
        </el-form-item>
        <el-alert
          type="info"
          :closable="false"
          show-icon
          title="修改来源后，详情页的「从仓库拉取」将按新配置执行；已有代码版本不受影响"
        />
      </el-form>
      <template #footer>
        <el-button @click="editSourceVisible = false">取消</el-button>
        <el-button type="primary" :loading="savingSource" @click="submitEditSource">保存</el-button>
      </template>
    </el-dialog>

    <!-- 启动测试确认对话框 -->
    <el-dialog v-model="runDialogVisible" title="启动自动化测试" width="560px" :close-on-click-modal="false">
      <el-form label-width="110px">
        <el-form-item label="代码版本">
          <span class="mono-text">{{ runDialogForm.versionName }}</span>
        </el-form-item>
        <el-form-item label="被测目标环境">
          <el-input
            v-model="runDialogForm.targetUrl"
            placeholder="http://192.168.1.100:8080（真实被测服务地址）"
          >
            <template #append>
              <el-button :loading="probing" @click="handleProbeUrl(runDialogForm.targetUrl)">连通测试</el-button>
            </template>
          </el-input>
          <div style="font-size: 12px; color: var(--el-text-color-secondary); margin-top: 4px">
            强烈建议配置真实服务地址。若留空，测试平台将尝试通过本地 Docker 容器启动。
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="runDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="executing" @click="confirmRunTest">
          <el-icon><VideoPlay /></el-icon>
          确认启动测试
        </el-button>
      </template>
    </el-dialog>
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
import { Plus, UploadFilled, Refresh, VideoPlay } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import type { UploadRequestOptions } from 'element-plus'
import { environmentApi, projectApi, projectCodeApi, testRunApi } from '@/api'

const SOURCE_LABELS: Record<string, string> = {
  github: 'GitHub',
  svn: 'SVN',
  upload: '本地上传',
}

export default defineComponent({
  name: 'ProjectsView',
  components: { Plus, UploadFilled, Refresh, VideoPlay },
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
        target_service_url: '',
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
      probing: false,

      // 启动测试弹窗
      runDialogVisible: false,
      runDialogForm: {
        versionId: '',
        versionName: '',
        targetUrl: '',
        sourceType: 'upload',
      },

      // M1：测试环境档案
      environments: [] as any[],
      envsLoading: false,
      envDialogVisible: false,
      envSaving: false,
      envForm: {
        id: '',
        name: '',
        description: '',
        base_url: '',
        healthcheck_path: '',
        auth_strategy: 'none',
        auth_token: '',
      },

      // 修改代码来源
      editSourceVisible: false,
      savingSource: false,
      editForm: {
        source_type: 'github',
        target_service_url: '',
        repo_url: '',
        github_token: '',
        branch: 'main',
        svn_url: '',
        svn_username: '',
        svn_password: '',
      },
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
        target_service_url: '',
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
    async handleProbeUrl(url?: string): Promise<void> {
      const target = (url || '').trim()
      if (!target) {
        ElMessage.warning('请先输入被测服务 URL')
        return
      }
      this.probing = true
      try {
        const res: any = await projectApi.probeUrl(target)
        const d = res?.data || {}
        if (d.reachable) {
          ElMessage.success(d.message || `连接成功: HTTP ${d.status_code} (${d.response_time_ms}ms)`)
        } else {
          ElMessage.error(d.message || `连接失败: ${d.error || '无法访问'}`)
        }
      } catch (err: any) {
        ElMessage.error(err?.message || '探测请求失败')
      } finally {
        this.probing = false
      }
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
          source_config: {},
        }
        if (this.createForm.target_service_url?.trim()) {
          payload.source_config.target_service_url = this.createForm.target_service_url.trim()
        }
        // 仓库配置随项目一起写入 source_config（后续「从仓库拉取」直接用）
        if (this.createForm.source_type === 'github' && this.createForm.repo_url) {
          payload.source_config = {
            ...payload.source_config,
            repo_url: this.createForm.repo_url,
            github_token: this.createForm.github_token || '',
            branch: this.createForm.branch || 'main',
          }
        } else if (this.createForm.source_type === 'svn' && this.createForm.svn_url) {
          payload.source_config = {
            ...payload.source_config,
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
      this.loadEnvironments()
    },
    // ============ M1：测试环境档案 ============
    async loadEnvironments(): Promise<void> {
      if (!this.current) return
      this.envsLoading = true
      try {
        const res: any = await environmentApi.list(this.current.id)
        this.environments = res?.data?.list || []
      } catch {
        this.environments = []
      } finally {
        this.envsLoading = false
      }
    },
    openEnvDialog(env?: any): void {
      this.envForm = {
        id: env?.id || '',
        name: env?.name || '',
        description: env?.description || '',
        base_url: env?.base_url || '',
        healthcheck_path: env?.healthcheck_path || '',
        auth_strategy: env?.auth_strategy || 'none',
        auth_token: '',
      }
      this.envDialogVisible = true
    },
    async submitEnv(): Promise<void> {
      if (!this.envForm.name.trim()) {
        ElMessage.warning('请输入环境名称')
        return
      }
      if (!this.envForm.base_url.trim()) {
        ElMessage.warning('请输入被测地址')
        return
      }
      this.envSaving = true
      try {
        const payload: any = {
          name: this.envForm.name.trim(),
          description: this.envForm.description?.trim() || undefined,
          base_url: this.envForm.base_url.trim(),
          healthcheck_path: this.envForm.healthcheck_path?.trim() || '',
          auth_strategy: this.envForm.auth_strategy,
          auth_config: this.envForm.auth_token ? { token: this.envForm.auth_token } : {},
        }
        if (this.envForm.id) {
          await environmentApi.update(this.envForm.id, payload)
          ElMessage.success('环境已更新（修改后需重新发布才对执行生效）')
        } else {
          await environmentApi.create(this.current.id, payload)
          ElMessage.success('环境草稿已创建，发布后可被执行选择')
        }
        this.envDialogVisible = false
        this.loadEnvironments()
      } catch {
        /* 拦截器已提示 */
      } finally {
        this.envSaving = false
      }
    },
    async checkEnv(row: any): Promise<void> {
      row._checking = true
      try {
        const res: any = await environmentApi.healthcheck(row.id)
        const d = res?.data || {}
        if (d.health_status === 'healthy') {
          ElMessage.success(`健康检查通过：${d.health_detail || ''}`)
        } else {
          ElMessage.warning(`健康检查${d.health_status === 'skipped' ? '跳过' : '未通过'}：${d.health_detail || ''}`)
        }
      } catch {
        /* 拦截器已提示 */
      } finally {
        row._checking = false
      }
    },
    async publishEnv(row: any): Promise<void> {
      row._publishing = true
      try {
        const res: any = await environmentApi.publish(row.id)
        const d = res?.data || {}
        const health = d.health?.status || 'unknown'
        if (health === 'healthy') {
          ElMessage.success(`环境已发布（修订版 r${d.revision}，健康检查正常）`)
        } else {
          ElMessage.warning(`环境已发布（修订版 r${d.revision}），但健康检查：${d.health?.detail || health}`)
        }
        this.loadEnvironments()
      } catch {
        /* 拦截器已提示 */
      } finally {
        row._publishing = false
      }
    },
    formatCoverageInfo(project: any): string {
      const cfg = project?.coverage_config || project?.source_config?.coverage_config
      if (!cfg) return '未单独配置（将使用被测服务或自动推断）'
      if (cfg.enabled === false) return '已禁用自动采集'
      if (cfg.strategy === 'remote_tcp') {
        return `JaCoCo TCP (${cfg.probe_host || '默认'}:${cfg.probe_port || 6300})`
      }
      if (cfg.strategy === 'http_dump') {
        return `HTTP Dump (${cfg.dump_url || '未填URL'})`
      }
      return `${cfg.tool || 'jacoco'} (${cfg.strategy || '自动扫描'})`
    },
    async openEditSource(): Promise<void> {
      if (!this.current) return
      // 拉取项目详情回填脱敏配置（token 显示为 ****，留空保存则保持原值）
      try {
        const res: any = await projectApi.get(this.current.id)
        const d = res?.data || {}
        const cfg = d.source_config || {}
        this.editForm = {
          source_type: d.source_type || 'upload',
          target_service_url: cfg.target_service_url || d.target_service_url || '',
          repo_url: cfg.repo_url || '',
          github_token: '',
          branch: cfg.branch || 'main',
          svn_url: cfg.svn_url || '',
          svn_username: cfg.svn_username || '',
          svn_password: '',
        }
        this.editSourceVisible = true
      } catch {
        ElMessage.error('加载项目配置失败')
      }
    },
    async submitEditSource(): Promise<void> {
      if (!this.current) return
      if (this.editForm.source_type === 'github' && !this.editForm.repo_url) {
        ElMessage.warning('请填写 GitHub 仓库地址')
        return
      }
      if (this.editForm.source_type === 'svn' && !this.editForm.svn_url) {
        ElMessage.warning('请填写 SVN 地址')
        return
      }
      this.savingSource = true
      try {
        const payload: any = { source_type: this.editForm.source_type, source_config: {} }
        if (this.editForm.target_service_url !== undefined) {
          payload.source_config.target_service_url = this.editForm.target_service_url.trim()
        }
        if (this.editForm.source_type === 'github') {
          payload.source_config = {
            ...payload.source_config,
            repo_url: this.editForm.repo_url,
            github_token: this.editForm.github_token || '',
            branch: this.editForm.branch || 'main',
          }
        } else if (this.editForm.source_type === 'svn') {
          payload.source_config = {
            ...payload.source_config,
            svn_url: this.editForm.svn_url,
            svn_username: this.editForm.svn_username || '',
            svn_password: this.editForm.svn_password || '',
          }
        }
        await projectApi.update(this.current.id, payload)
        ElMessage.success('项目配置已更新')
        this.editSourceVisible = false
        await this.loadProjects()
        const updated = this.projects.find((p: any) => p.id === this.current.id)
        if (updated) this.current = updated
      } catch {
        /* 拦截器已提示 */
      } finally {
        this.savingSource = false
      }
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
    runOnVersion(row: any): void {
      if (!this.current) return
      const defaultUrl = this.current.target_service_url || (this.current.source_config && this.current.source_config.target_service_url) || ''
      this.runDialogForm = {
        versionId: row.id,
        versionName: row.note || row.version_id?.substring(0, 12) || '当前版本',
        targetUrl: defaultUrl,
        sourceType: row.source_type || 'upload',
      }
      this.runDialogVisible = true
    },
    async confirmRunTest(): Promise<void> {
      if (!this.current) return
      this.executing = true
      try {
        const res: any = await testRunApi.create({
          mode: 'auto',
          source_type: this.runDialogForm.sourceType || 'upload',
          project_id: this.current.id,
          code_version_id: this.runDialogForm.versionId,
          target_service_url: this.runDialogForm.targetUrl?.trim() || undefined,
        })
        const runId = res?.data?.test_run_id || res?.data?.id || res?.test_run_id
        ElMessage.success('测试任务已启动，正在跳转至任务详情跟踪实时流水线...')
        this.runDialogVisible = false
        this.detailVisible = false
        if (runId) {
          this.$router.push({ path: '/test-run', query: { run_id: runId } })
        } else {
          this.$router.push('/test-run')
        }
      } catch {
        /* 拦截器已提示 */
      } finally {
        this.executing = false
      }
    },
  },
  async mounted() {
    await this.loadProjects()
    const targetId = this.$route.query.id as string
    if (targetId) {
      const match = this.projects.find((p: any) => p.id === targetId)
      if (match) {
        this.openDetail(match)
      }
    }
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
.env-tip {
  margin-top: 6px;
  padding: 8px 12px;
  background: #f4f8ff;
  border-radius: 4px;
  font-size: 12px;
  color: #909399;
  line-height: 1.8;
}
</style>
