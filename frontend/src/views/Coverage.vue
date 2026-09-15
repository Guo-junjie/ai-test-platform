<template>
  <div class="coverage-dashboard">
    <!-- 顶部：项目 + 报告选择 -->
    <el-card shadow="hover" class="filter-card">
      <div class="filter-row">
        <div class="filter-item">
          <span class="label">项目</span>
          <el-select
            v-model="projectId"
            placeholder="选择项目"
            filterable
            clearable
            style="width: 280px"
            @change="onProjectChange"
          >
            <el-option v-for="p in projects" :key="p.id" :label="p.name" :value="p.id" />
          </el-select>
        </div>
        <div class="filter-item">
          <span class="label">报告</span>
          <el-select
            v-model="selectedReportId"
            placeholder="选择覆盖率报告"
            filterable
            clearable
            :loading="loadingReports"
            :disabled="!projectId"
            style="width: 380px"
            @change="onReportChange"
          >
            <el-option
              v-for="r in reports"
              :key="r.id"
              :label="reportLabel(r)"
              :value="r.id"
            />
          </el-select>
        </div>
        <el-tooltip content="开启后按已配置的采集方式执行；Java 自动采集还需配置 Agent 并由 CI 部署 JaCoCo 测试服务" placement="top">
          <div class="cov-switch">
            <span class="cov-switch-label">自动采集</span>
            <el-switch
              v-model="autoCoverage"
              :loading="covSwitchLoading"
              :disabled="!projectId || !canManage"
              @change="onAutoCoverageChange"
            />
          </div>
        </el-tooltip>
        <el-button :disabled="!projectId" @click="refreshAll">刷新</el-button>
        <el-button type="success" :icon="Odometer" :loading="collecting" :disabled="!projectId" @click="handleCollectNow">按配置采集</el-button>
        <el-button :icon="Setting" :disabled="!projectId" @click="openProbeConfigDrawer">探针配置</el-button>
        <el-button type="primary" :icon="UploadFilled" :disabled="!projectId" @click="openUploadDialog">上传报告</el-button>
      </div>
    </el-card>

    <el-card v-if="projectId && coverageRuns.length" shadow="never">
      <template #header>测试任务覆盖率会话</template>
      <el-table :data="coverageRuns" size="small" max-height="240">
        <el-table-column label="测试任务" width="130">
          <template #default="{ row }">{{ row.test_run_id.slice(0, 8) }}</template>
        </el-table-column>
        <el-table-column label="采集状态" width="130">
          <template #default="{ row }">
            <el-tag :type="coverageStatusType(row.status)">{{ coverageStatusLabel(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="代码行覆盖率" width="150">
          <template #default="{ row }">{{ row.line_rate == null ? '暂无产物' : `${row.line_rate}% (${row.covered_lines}/${row.total_lines})` }}</template>
        </el-table-column>
        <el-table-column prop="error_message" label="采集说明" show-overflow-tooltip />
        <el-table-column label="详情" width="90">
          <template #default="{ row }"><el-button link type="primary" @click="showCoverageRun(row.test_run_id)">查看</el-button></template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="runDialogVisible" title="覆盖率采集详情" width="650px">
      <template v-if="selectedCoverageRun">
        <p>测试任务 {{ selectedCoverageRun.test_run_id }} · {{ coverageStatusLabel(selectedCoverageRun.status) }}</p>
        <el-alert v-if="selectedCoverageRun.error_message" :title="selectedCoverageRun.error_message" type="warning" :closable="false" />
        <el-table :data="selectedCoverageRun.services || []" style="margin-top: 12px">
          <el-table-column prop="name" label="服务" />
          <el-table-column label="状态"><template #default="{ row }">{{ coverageStatusLabel(row.status) }}</template></el-table-column>
          <el-table-column prop="deployed_commit_sha" label="部署版本" show-overflow-tooltip />
          <el-table-column label="报告"><template #default="{ row }"><el-button v-if="row.report_id" link type="primary" @click="selectServiceReport(row.report_id)">查看报告</el-button><span v-else>无产物</span></template></el-table-column>
          <el-table-column prop="error_message" label="错误" show-overflow-tooltip />
        </el-table>
      </template>
    </el-dialog>

    <template v-if="!projectId">
      <el-empty description="请先选择项目" />
    </template>

    <template v-else-if="!latestReportId && reports.length === 0 && !loadingReports">
      <el-card shadow="hover" class="empty-card">
        <el-empty description="该项目暂无覆盖率报告">
          <el-button type="primary" :icon="Setting" @click="openProbeConfigDrawer">配置自动采集</el-button>
          <el-button :icon="UploadFilled" @click="openUploadDialog">上传覆盖率报告</el-button>
          <div class="empty-tip">
            Java 常驻服务需在 CI 部署时加载 JaCoCo，并配置 Agent 与匹配版本的 classfiles；测试任务结束后才会出现关联报告。也支持手动上传 coverage.py / JaCoCo / Cobertura XML、Go coverprofile。
          </div>
        </el-empty>
      </el-card>
    </template>

    <template v-else>
      <!-- 报告元数据条 -->
      <div v-if="dashboard?.latest" class="report-meta-bar">
        <el-tag :type="dashboard.latest.source === 'auto' ? 'success' : 'info'" size="small" effect="dark">
          {{ dashboard.latest.source === 'auto' ? '自动采集' : '手动上传' }}
        </el-tag>
        <span class="meta-item">工具: <b>{{ dashboard.latest.tool }}</b></span>
        <span class="meta-item" v-if="dashboard.latest.language">语言: {{ dashboard.latest.language }}</span>
        <span class="meta-item" v-if="dashboard.latest.test_run_id">
          关联测试任务:
          <el-link type="primary" :href="`/#/test-run`" target="_blank">
            {{ String(dashboard.latest.test_run_id).substring(0, 8) }}
          </el-link>
        </span>
        <span class="meta-item" v-if="dashboard.latest.created_at">
          采集时间: {{ String(dashboard.latest.created_at).slice(0, 19).replace('T', ' ') }}
        </span>
      </div>

      <!-- 4 张指标卡 -->
      <el-row :gutter="16" class="metric-row">
        <el-col :xs="12" :sm="6">
          <el-card shadow="hover" class="metric-card">
            <div class="metric-label">{{ dashboard?.latest?.language === 'go' ? '语句覆盖率' : '行覆盖率' }}</div>
            <div class="metric-value" :class="rateClass(dashboard?.latest?.line_rate)">
              {{ fmt(dashboard?.latest?.line_rate) }}<span class="metric-unit">%</span>
            </div>
            <div class="metric-diff" v-if="dashboard?.diff_line_rate != null">
              <el-tag
                :type="dashboard.diff_line_rate > 0 ? 'success' : dashboard.diff_line_rate < 0 ? 'danger' : 'info'"
                size="small"
                effect="plain"
              >
                {{ dashboard.diff_line_rate > 0 ? '▲' : dashboard.diff_line_rate < 0 ? '▼' : '—' }}
                {{ Math.abs(dashboard.diff_line_rate).toFixed(2) }}
              </el-tag>
              <span class="metric-diff-label">较上次</span>
            </div>
          </el-card>
        </el-col>
        <el-col :xs="12" :sm="6">
          <el-card shadow="hover" class="metric-card">
            <div class="metric-label">分支覆盖率</div>
            <div class="metric-value" :class="rateClass(dashboard?.latest?.branch_rate)">
              {{ dashboard?.latest?.branch_rate == null ? '未提供' : fmt(dashboard?.latest?.branch_rate) }}<span v-if="dashboard?.latest?.branch_rate != null" class="metric-unit">%</span>
            </div>
            <div class="metric-diff" v-if="dashboard?.diff_branch_rate != null">
              <el-tag
                :type="dashboard.diff_branch_rate > 0 ? 'success' : dashboard.diff_branch_rate < 0 ? 'danger' : 'info'"
                size="small"
                effect="plain"
              >
                {{ dashboard.diff_branch_rate > 0 ? '▲' : dashboard.diff_branch_rate < 0 ? '▼' : '—' }}
                {{ Math.abs(dashboard.diff_branch_rate).toFixed(2) }}
              </el-tag>
              <span class="metric-diff-label">较上次</span>
            </div>
          </el-card>
        </el-col>
        <el-col :xs="12" :sm="6">
          <el-card shadow="hover" class="metric-card">
            <div class="metric-label">{{ dashboard?.latest?.language === 'go' ? '已覆盖语句 / 总语句' : '已覆盖行 / 总行' }}</div>
            <div class="metric-value neutral">
              {{ dashboard?.latest?.covered_lines ?? 0 }}
              <span class="metric-unit-sm">/ {{ dashboard?.latest?.total_lines ?? 0 }}</span>
            </div>
            <div class="metric-diff">
              <span class="metric-diff-label">覆盖分支 {{ dashboard?.latest?.covered_branches ?? 0 }} / {{ dashboard?.latest?.total_branches ?? 0 }}</span>
            </div>
          </el-card>
        </el-col>
        <el-col :xs="12" :sm="6">
          <el-card shadow="hover" class="metric-card">
            <div class="metric-label">报告 / 文件</div>
            <div class="metric-value neutral">
              {{ dashboard?.report_count ?? 0 }}
              <span class="metric-unit-sm">/ {{ dashboard?.file_count ?? 0 }}</span>
            </div>
            <div class="metric-diff">
              <span class="metric-diff-label">项目内累计</span>
            </div>
          </el-card>
        </el-col>
      </el-row>

      <!-- 趋势图 -->
      <el-card shadow="hover" class="trend-card">
        <template #header>
          <span>覆盖率趋势（最近 30 天）</span>
        </template>
        <TrendChart
          v-if="trend.labels && trend.labels.length"
          :labels="trend.labels"
          :series="trendSeries"
          :height="240"
          y-axis-name="%"
        />
        <el-empty v-else description="近 30 天暂无报告" :image-size="80" />
      </el-card>

      <!-- 文件表 -->
      <el-card shadow="hover" class="files-card">
        <template #header>
          <div class="files-header">
            <span>文件级明细（共 {{ filesTotal }} 个文件）</span>
            <div class="files-tools">
              <el-input
                v-model="fileQuery"
                placeholder="搜索文件路径"
                clearable
                size="small"
                style="width: 240px"
                @input="onFileQueryChange"
              />
              <el-select
                v-model="fileSort"
                size="small"
                style="width: 120px"
                @change="onFileSortChange"
              >
                <el-option :label="dashboard?.latest?.language === 'go' ? '按语句率' : '按行率'" value="rate" />
                <el-option label="按路径" value="path" />
                <el-option :label="dashboard?.latest?.language === 'go' ? '按总语句' : '按总行'" value="total_lines" />
              </el-select>
              <el-select
                v-model="fileOrder"
                size="small"
                style="width: 90px"
                @change="onFileSortChange"
              >
                <el-option label="升序" value="asc" />
                <el-option label="降序" value="desc" />
              </el-select>
            </div>
          </div>
        </template>
        <el-table
          v-loading="loadingFiles"
          :data="files"
          size="small"
          border
          stripe
          empty-text="该报告无文件明细"
          @row-click="onFileRowClick"
        >
          <el-table-column prop="path" label="文件路径" min-width="280" show-overflow-tooltip>
            <template #default="{ row }">
              <span class="file-path">{{ row.path }}</span>
            </template>
          </el-table-column>
          <el-table-column :label="dashboard?.latest?.language === 'go' ? '语句覆盖' : '行覆盖'" width="200" align="center">
            <template #default="{ row }">
              <el-progress
                :percentage="fmt(row.line_rate)"
                :color="progressColor(row.line_rate)"
                :stroke-width="10"
                :show-text="false"
                style="width: 110px; display: inline-block; vertical-align: middle; margin-right: 8px"
              />
              <span :class="rateClass(row.line_rate)">{{ fmt(row.line_rate) }}%</span>
            </template>
          </el-table-column>
          <el-table-column label="分支覆盖" width="120" align="center">
            <template #default="{ row }">
              <span v-if="row.branch_rate == null" class="text-muted">-</span>
              <span v-else :class="rateClass(row.branch_rate)">{{ fmt(row.branch_rate) }}%</span>
            </template>
          </el-table-column>
          <el-table-column :label="dashboard?.latest?.language === 'go' ? '覆盖语句' : '覆盖行'" width="100" align="center">
            <template #default="{ row }">
              {{ row.covered_lines }}/{{ row.total_lines }}
            </template>
          </el-table-column>
          <el-table-column label="操作" width="80" fixed="right">
            <template #default="{ row }">
              <el-button size="small" text type="primary" @click.stop="onFileRowClick(row)">查看明细</el-button>
            </template>
          </el-table-column>
        </el-table>
        <el-pagination
          v-if="filesTotal > pageSize"
          class="files-pagination"
          :current-page="page"
          :page-size="pageSize"
          :total="filesTotal"
          :page-sizes="[20, 50, 100, 200]"
          layout="total, sizes, prev, pager, next, jumper"
          @current-change="onPageChange"
          @size-change="onPageSizeChange"
        />
      </el-card>
    </template>

    <!-- 源码行级覆盖 抽屉 -->
    <el-drawer
      v-model="drawerOpen"
      :title="drawerTitle"
      direction="rtl"
      size="640px"
      destroy-on-close
    >
      <div v-loading="loadingSource" class="source-drawer-body">
        <div v-if="sourceData" class="source-summary">
          <el-tag :type="rateType(sourceData.line_rate)" effect="plain" size="large">
            {{ dashboard?.latest?.language === 'go' ? '语句覆盖' : '行覆盖' }} {{ fmt(sourceData.line_rate) }}%
          </el-tag>
          <el-tag
            v-if="sourceData.branch_rate != null"
            :type="rateType(sourceData.branch_rate)"
            effect="plain"
            size="large"
            style="margin-left: 8px"
          >
            分支覆盖 {{ fmt(sourceData.branch_rate) }}%
          </el-tag>
          <el-tag effect="plain" size="large" style="margin-left: 8px">
            {{ sourceData.covered_lines }} / {{ sourceData.total_lines }} {{ dashboard?.latest?.language === 'go' ? '语句' : '行' }}
          </el-tag>
        </div>
        <div v-if="sourceData" class="legend">
          <span class="legend-item"><span class="dot covered"></span>已覆盖</span>
          <span class="legend-item"><span class="dot partial"></span>分支部分覆盖</span>
          <span class="legend-item"><span class="dot uncovered"></span>未覆盖</span>
        </div>
        <div v-if="sourceData" class="source-line-list">
          <div
            v-for="line in sourceData.lines"
            :key="line.number"
            class="source-line"
            :class="lineClass(line)"
          >
            <span class="line-no">{{ line.number }}</span>
            <span class="line-icon">{{ lineIcon(line) }}</span>
            <span class="line-hits">hits={{ line.hits }}</span>
            <span v-if="line.total_branches > 0" class="line-branch">
              分支 {{ line.covered_branches }}/{{ line.total_branches }}
            </span>
          </div>
          <el-empty v-if="!sourceData.lines.length" description="该文件无行级数据" />
        </div>
      </div>
    </el-drawer>

    <!-- 上传覆盖率报告 对话框 -->
    <el-dialog
      v-model="uploadDialogVisible"
      title="上传覆盖率报告"
      width="560px"
      :close-on-click-modal="false"
      destroy-on-close
    >
      <el-form label-width="100px" :model="uploadForm">
        <el-form-item label="工具" required>
          <el-select v-model="uploadForm.tool" style="width: 100%">
            <el-option label="coverage.py (Python)" value="coverage.py" />
            <el-option label="JaCoCo (Java)" value="jacoco" />
            <el-option label="istanbul / nyc (Node)" value="istanbul" />
            <el-option label="Cobertura (通用)" value="cobertura" />
            <el-option label="Go coverprofile" value="go_cover" />
          </el-select>
        </el-form-item>
        <el-form-item label="语言">
          <el-input v-model="uploadForm.language" placeholder="可选：python / java / javascript / go" />
        </el-form-item>
        <el-form-item label="报告文件" required>
          <el-upload
            :auto-upload="false"
            :limit="1"
            :show-file-list="true"
            accept=".xml,.out"
            :on-change="onUploadFileChange"
            :on-exceed="() => ElMessage.warning('每次仅可上传一个文件')"
          >
            <el-button :icon="UploadFilled">选择文件</el-button>
            <template #tip>
              <div class="el-upload__tip">
                Python: <code>coverage xml</code>；Java: <code>jacoco:report</code>；Go: <code>go test -coverprofile=coverage.out ./...</code>（≤ 20MB）。Go 报告为语句覆盖率，不提供分支率。
              </div>
            </template>
          </el-upload>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="uploadDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="uploading" :disabled="!uploadForm.file" @click="submitUpload">
          解析并入库
        </el-button>
      </template>
    </el-dialog>

    <!-- 探针配置抽屉 -->
    <el-drawer v-model="probeDrawerVisible" title="代码覆盖率采集配置" size="520px">
      <el-form label-width="110px" label-position="left">
        <el-form-item label="自动采集">
          <el-switch v-model="probeForm.enabled" active-text="执行测试时自动采集" />
        </el-form-item>
        <el-form-item label="采集方式">
          <el-select v-model="probeForm.strategy" style="width: 100%">
            <el-option label="远程 Agent（Java 常驻 / Python、Go 临时实例）" value="agent" />
            <el-option label="现有 XML 报告地址" value="http_dump" />
            <el-option label="现有工作空间报告" value="repo_file" />
          </el-select>
        </el-form-item>
        <template v-if="probeForm.strategy === 'agent'">
          <el-alert title="Java：Jenkins 先部署已加载 JaCoCo 的常驻测试服务；测试前清零，测试后导出 XML，业务服务保持运行。Python/Go：由 Agent 启动独立实例。Agent 服务及构建产物路径仅由主机管理员登记。" type="info" :closable="false" style="margin-bottom: 16px" />
          <el-form-item label="严格模式"><el-switch v-model="probeForm.required" /><span style="margin-left: 8px">采集失败则测试任务失败</span></el-form-item>
          <el-form-item label="最低行覆盖率"><el-input-number v-model="probeForm.min_line_rate" :min="0" :max="100" :precision="2" placeholder="不限制" /><span style="margin-left: 8px">留空不限制；严格模式下未达标会使测试失败</span></el-form-item>
          <el-form-item label="最低分支率"><el-input-number v-model="probeForm.min_branch_rate" :min="0" :max="100" :precision="2" placeholder="不限制" /><span style="margin-left: 8px">JaCoCo 可提供分支覆盖率</span></el-form-item>
          <el-form-item label="服务名"><el-input v-model="probeForm.agent_service_name" placeholder="与 Agent 登记名一致" /></el-form-item>
          <el-form-item label="服务语言"><el-select v-model="probeForm.agent_language" style="width: 100%"><el-option label="Java（JaCoCo 常驻服务）" value="java" /><el-option label="Python（coverage.py）" value="python" /><el-option label="Go（go build -cover）" value="go" /></el-select></el-form-item>
          <el-form-item label="Agent URL"><el-input v-model="probeForm.agent_url" placeholder="https://coverage-agent.example.com" /></el-form-item>
          <el-form-item label="令牌环境变量"><el-input v-model="probeForm.token_env" placeholder="COVERAGE_AGENT_TOKEN" /></el-form-item>
          <el-form-item label="测试入口"><el-switch v-model="probeForm.agent_primary" /></el-form-item>
          <template v-for="(item, index) in extraAgentServices" :key="index">
            <el-divider>附加服务 {{ index + 1 }}</el-divider>
            <el-form-item label="服务名"><el-input v-model="item.name" /></el-form-item>
            <el-form-item label="服务语言"><el-select v-model="item.language" style="width: 100%"><el-option label="Java（JaCoCo 常驻服务）" value="java" /><el-option label="Python（coverage.py）" value="python" /><el-option label="Go（go build -cover）" value="go" /></el-select></el-form-item>
            <el-form-item label="Agent URL"><el-input v-model="item.agent_url" /></el-form-item>
            <el-form-item label="令牌环境变量"><el-input v-model="item.token_env" /></el-form-item>
            <el-form-item label="测试入口"><el-switch v-model="item.primary" /></el-form-item>
            <el-form-item><el-button type="danger" text @click="extraAgentServices.splice(index, 1)">移除服务</el-button></el-form-item>
          </template>
          <el-form-item><el-button @click="addAgentService">添加服务</el-button></el-form-item>
          <el-form-item><el-button :loading="probing" @click="testAgentConnectivity">校验 Agent</el-button></el-form-item>
        </template>
        <template v-else>
        <el-form-item label="覆盖率工具">
          <el-radio-group v-model="probeForm.tool">
            <el-radio-button value="jacoco">JaCoCo</el-radio-button>
            <el-radio-button value="coverage.py">coverage.py</el-radio-button>
            <el-radio-button value="cobertura">Cobertura</el-radio-button>
            <el-radio-button value="go_cover">Go coverprofile</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-alert v-if="probeForm.strategy === 'remote_tcp'" title="JaCoCo TCP 只返回 .exec 探针位图，无法直接计算代码行覆盖率。请改用 XML 报告地址。" type="warning" :closable="false" />
        <template v-if="probeForm.strategy === 'remote_tcp'">
          <el-form-item label="探针主机 IP">
            <el-input v-model="probeForm.probe_host" placeholder="如 192.168.125.128 或被测服务 IP" />
          </el-form-item>
          <el-form-item label="探针 TCP 端口">
            <el-input-number v-model="probeForm.probe_port" :min="1" :max="65535" style="width: 100%" />
          </el-form-item>
        </template>
        <template v-if="probeForm.strategy === 'http_dump'">
          <el-form-item label="Dump 完整 URL">
            <el-input v-model="probeForm.dump_url" placeholder="如 http://192.168.125.128:8080/actuator/jacoco" />
          </el-form-item>
        </template>
        <el-form-item>
          <el-button type="info" plain :loading="probing" :disabled="probeForm.strategy !== 'http_dump'" @click="testProbeConnectivity">
            校验报告来源
          </el-button>
        </el-form-item>
        </template>
      </el-form>
      <template #footer>
        <el-button @click="probeDrawerVisible = false">取消</el-button>
        <el-button type="primary" :loading="savingConfig" @click="saveProbeConfig">保存配置</el-button>
      </template>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { CHART_COLORS } from '@/styles/chartPalette'
import { ref, computed, watch, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { UploadFilled, Odometer, Setting } from '@element-plus/icons-vue'
import { coverageApi, projectApi, projectConfigApi } from '@/api'
import { useAuthStore } from '@/stores'
import TrendChart from '@/components/TrendChart.vue'

const route = useRoute()

// ====== 状态 ======
const projects = ref<any[]>([])
const projectId = ref<string>('')
// R2：从报告页跳转时按测试任务过滤（query.test_run_id）
const runFilter = ref<string>('')
const authStore = useAuthStore()
const canManage = computed(() =>
  ['super_admin', 'admin', 'test_manager'].includes(authStore.role)
)
const autoCoverage = ref<boolean>(true)
watch(projectId, () => void loadCoverageSwitch())
const covSwitchLoading = ref<boolean>(false)

async function loadCoverageSwitch(): Promise<void> {
  if (!projectId.value) return
  try {
    const res: any = await projectConfigApi.getCIConfig(projectId.value)
    if (res?.code === 0 && res?.data) {
      autoCoverage.value = res.data.auto_coverage !== false
    }
  } catch { /* 忽略，保持默认 */ }
}

async function onAutoCoverageChange(val: boolean): Promise<void> {
  try {
    covSwitchLoading.value = true
    const res: any = await projectConfigApi.setCoverageConfig(projectId.value, val)
    if (res?.code === 0) {
      ElMessage.success(val ? '已开启本项目自动覆盖率采集' : '已关闭本项目自动覆盖率采集')
    } else {
      autoCoverage.value = !val
      ElMessage.error(res?.message || '设置失败')
    }
  } catch {
    autoCoverage.value = !val
  } finally {
    covSwitchLoading.value = false
  }
}
const reports = ref<any[]>([])
const coverageRuns = ref<any[]>([])
const selectedCoverageRun = ref<any>(null)
const runDialogVisible = ref(false)
const selectedReportId = ref<string>('')
const latestReportId = ref<string>('')  // 看板数据绑定的报告（默认最新一份）
const loadingReports = ref(false)

const dashboard = ref<any>(null)
const trend = ref<any>({ labels: [], line_rate: [], branch_rate: [] })
const trendSeries = computed(() => {
  const series = [{ name: '行/语句覆盖率', data: trend.value.line_rate || [], color: CHART_COLORS.success }]
  if ((trend.value.branch_rate || []).some((rate: number | null) => rate != null)) {
    series.push({ name: '分支覆盖率', data: trend.value.branch_rate, color: CHART_COLORS.primary })
  }
  return series
})

const files = ref<any[]>([])
const filesTotal = ref(0)
const loadingFiles = ref(false)
const fileQuery = ref('')
const fileSort = ref<'rate' | 'path' | 'total_lines'>('rate')
const fileOrder = ref<'asc' | 'desc'>('asc')
const page = ref(1)
const pageSize = ref(50)

// 源码抽屉
const drawerOpen = ref(false)
const drawerTitle = ref('')
const sourceData = ref<any>(null)
const loadingSource = ref(false)

// 上传对话框
const uploadDialogVisible = ref(false)
const uploading = ref(false)
const uploadForm = ref<{
  tool: string
  language: string
  file: File | null
}>({
  tool: 'coverage.py',
  language: '',
  file: null,
})

// 探针即时采集与配置
const collecting = ref(false)
const probeDrawerVisible = ref(false)
const probing = ref(false)
const savingConfig = ref(false)
const extraAgentServices = ref<any[]>([])
const probeForm = ref<{
  enabled: boolean
  tool: string
  strategy: string
  probe_host: string
  probe_port: number
  dump_url: string
  required: boolean
  min_line_rate: number | null
  min_branch_rate: number | null
  agent_service_name: string
  agent_language: string
  agent_url: string
  token_env: string
  agent_primary: boolean
}>({
  enabled: true,
  tool: 'jacoco',
    strategy: 'agent',
  probe_host: '',
  probe_port: 6300,
  dump_url: '',
    required: true,
    min_line_rate: null,
    min_branch_rate: null,
  agent_service_name: '',
    agent_language: 'java',
  agent_url: '',
  token_env: 'COVERAGE_AGENT_TOKEN',
  agent_primary: true,
})

function openProbeConfigDrawer() {
  if (!projectId.value) {
    ElMessage.warning('请先选择项目')
    return
  }
  const curProj = projects.value.find((p) => p.id === projectId.value)
  const cfg = curProj?.coverage_config || curProj?.source_config?.coverage_config || {}
  const agent = cfg.services?.[0] || {}
    extraAgentServices.value = (cfg.services || []).slice(1).map((item: any) => ({ ...item, language: item.language || 'java' }))
  probeForm.value = {
    enabled: cfg.enabled !== false,
    tool: cfg.tool || 'cobertura',
    strategy: cfg.services?.length || !cfg.strategy || cfg.strategy === 'remote_tcp' ? 'agent' : cfg.strategy,
    probe_host: cfg.probe_host || curProj?.target_service_url?.replace(/^https?:\/\//, '').split(':')[0] || '',
    probe_port: cfg.probe_port || 6300,
    dump_url: cfg.dump_url || '',
    required: cfg.required !== false,
    min_line_rate: cfg.min_line_rate ?? null,
    min_branch_rate: cfg.min_branch_rate ?? null,
    agent_service_name: agent.name || '',
    agent_language: agent.language || 'java',
    agent_url: agent.agent_url || '',
    token_env: agent.token_env || 'COVERAGE_AGENT_TOKEN',
    agent_primary: agent.primary !== false,
  }
  probeDrawerVisible.value = true
}

async function testProbeConnectivity() {
  probing.value = true
  try {
    const res: any = await coverageApi.probe({
      strategy: probeForm.value.strategy,
      host: probeForm.value.probe_host,
      port: probeForm.value.probe_port,
      dump_url: probeForm.value.dump_url,
    })
    const d = res?.data || {}
    if (d.ok) {
      ElMessage.success(`探针连接成功！${d.message || ''}`)
    } else {
      ElMessage.error(`探针连接失败：${d.message || '网络或端口不可达'}`)
    }
  } catch (e: any) {
    ElMessage.error(`测试失败：${e?.message || '请求异常'}`)
  } finally {
    probing.value = false
  }
}

function agentPayload() {
  return {
    name: probeForm.value.agent_service_name.trim(),
    agent_url: probeForm.value.agent_url.trim(),
    token_env: probeForm.value.token_env.trim(),
    language: probeForm.value.agent_language,
    tool: agentTool(probeForm.value.agent_language),
    primary: probeForm.value.agent_primary,
  }
}

function agentTool(language: string) {
  return language === 'java' ? 'jacoco' : language === 'go' ? 'go_cover' : 'coverage.py'
}

function addAgentService() {
  extraAgentServices.value.push({ name: '', agent_url: '', token_env: 'COVERAGE_AGENT_TOKEN',
    language: 'python', tool: 'coverage.py', primary: false })
}

async function testAgentConnectivity() {
  probing.value = true
  try {
    const res: any = await coverageApi.probeAgent(agentPayload())
    ElMessage.success(res?.data?.status === 'READY' ? 'Agent 已就绪' : 'Agent 未就绪')
  } catch (e: any) {
    ElMessage.error(e?.message || 'Agent 校验失败')
  } finally {
    probing.value = false
  }
}

async function saveProbeConfig() {
  if (!projectId.value) return
  if (probeForm.value.strategy === 'agent' &&
      (!probeForm.value.agent_service_name.trim() || !probeForm.value.agent_url.trim() || !probeForm.value.token_env.trim())) {
    ElMessage.warning('请填写 Agent 服务名、地址和令牌环境变量')
    return
  }
  if (probeForm.value.strategy === 'agent') {
    const services = [agentPayload(), ...extraAgentServices.value.map((item) => ({ ...item, tool: agentTool(item.language) }))]
    if (services.some((item) => !item.name?.trim() || !item.agent_url?.trim() || !item.token_env?.trim())) {
      ElMessage.warning('请填写全部 Agent 服务的名称、地址和令牌环境变量')
      return
    }
    if (services.filter((item) => item.primary).length !== 1) {
      ElMessage.warning('请选择唯一的测试入口服务')
      return
    }
  }
  if (probeForm.value.strategy === 'remote_tcp') {
    ElMessage.warning('JaCoCo TCP .exec 不能直接计算行覆盖率，请选择 XML 报告地址')
    return
  }
  if (probeForm.value.strategy === 'http_dump' && !probeForm.value.dump_url.trim()) {
    ElMessage.warning('请填写返回覆盖率报告的完整 HTTP 地址')
    return
  }
  savingConfig.value = true
  try {
    const payload = {
      ...probeForm.value,
      tool: probeForm.value.strategy === 'agent' ? agentTool(probeForm.value.agent_language) : probeForm.value.tool,
      services: probeForm.value.strategy === 'agent' ? [agentPayload(), ...extraAgentServices.value.map((item) => ({ ...item, tool: agentTool(item.language) }))] : [],
    }
    const res: any = await coverageApi.updateConfig(projectId.value, payload)
    if (res?.code === 0) {
      ElMessage.success('探针配置已保存')
      const curProj = projects.value.find((p) => p.id === projectId.value)
      if (curProj) {
        curProj.coverage_config = { ...payload }
        if (!curProj.source_config) curProj.source_config = {}
        curProj.source_config.coverage_config = { ...payload }
      }
      probeDrawerVisible.value = false
    } else {
      ElMessage.error(res?.message || '保存失败')
    }
  } catch (e: any) {
    ElMessage.error(e?.message || '保存配置失败')
  } finally {
    savingConfig.value = false
  }
}

async function handleCollectNow() {
  if (!projectId.value) {
    ElMessage.warning('请先选择项目')
    return
  }
  collecting.value = true
  try {
    const res: any = await coverageApi.collect({ project_id: projectId.value })
    if (res?.code === 0) {
      ElMessage.success(res.message || '真实覆盖率报告已入库')
      selectedReportId.value = ''
      await refreshAll()
    } else {
      ElMessage.error(res?.message || '采集失败')
    }
  } catch (e: any) {
    ElMessage.error(e?.message || '采集异常')
  } finally {
    collecting.value = false
  }
}

// ====== 工具 ======
function fmt(v: any): string {
  if (v == null) return '0'
  return Number(v).toFixed(1)
}
function rateType(rate: number | null | undefined): any {
  const r = Number(rate || 0)
  if (r >= 80) return 'success'
  if (r >= 60) return 'warning'
  return 'danger'
}
function rateClass(rate: number | null | undefined): string {
  const r = Number(rate || 0)
  if (r >= 80) return 'rate-good'
  if (r >= 60) return 'rate-mid'
  return 'rate-bad'
}
function progressColor(rate: number | null | undefined): string {
  const r = Number(rate || 0)
  if (r >= 80) return CHART_COLORS.success
  if (r >= 60) return CHART_COLORS.warning
  return CHART_COLORS.danger
}
function reportLabel(r: any): string {
  const date = (r.created_at || '').slice(0, 16).replace('T', ' ')
  return `${date} · ${r.service_name ? `${r.service_name} · ` : ''}${r.tool} · ${r.language === 'go' ? '语句' : '行'} ${r.line_rate}% · ${r.covered_lines}/${r.total_lines}`
}
function coverageStatusLabel(status: string): string {
  return ({ PREPARING: '准备中', RUNNING: '采集中', COLLECTING: '解析中',
    COMPLETED: '已完成', PARTIAL: '部分成功', FAILED: '失败',
    NO_ARTIFACT: '无覆盖率产物', CANCELLED: '已取消' } as Record<string, string>)[status] || status
}
function coverageStatusType(status: string): 'success' | 'warning' | 'danger' | 'info' {
  return status === 'COMPLETED' ? 'success' : status === 'PARTIAL' || status === 'NO_ARTIFACT'
    ? 'warning' : status === 'FAILED' ? 'danger' : 'info'
}
async function loadCoverageRuns() {
  if (!projectId.value) return
  try {
    const res: any = await coverageApi.runs(projectId.value)
    coverageRuns.value = Array.isArray(res?.data) ? res.data : []
  } catch {
    coverageRuns.value = []
  }
}
async function showCoverageRun(testRunId: string) {
  try {
    const res: any = await coverageApi.run(testRunId)
    selectedCoverageRun.value = res?.data || null
    runDialogVisible.value = true
  } catch (e: any) {
    ElMessage.error(e?.message || '加载采集详情失败')
  }
}
async function selectServiceReport(reportId: string) {
  runDialogVisible.value = false
  selectedReportId.value = reportId
  await onReportChange()
}
function lineClass(line: any): string {
  if (line.hits > 0 && line.total_branches > 0 && line.covered_branches < line.total_branches) {
    return 'line-partial'
  }
  if (line.hits > 0) return 'line-covered'
  return 'line-uncovered'
}
function lineIcon(line: any): string {
  if (line.hits > 0 && line.total_branches > 0 && line.covered_branches < line.total_branches) return '◐'
  if (line.hits > 0) return '●'
  return '○'
}

// ====== 加载 ======
async function loadProjects() {
  try {
    const res: any = await projectApi.getList()
    const d = res?.data ?? res
    projects.value = Array.isArray(d) ? d : d?.list || d?.items || []
  } catch (e: any) {
    projects.value = []
    ElMessage.error('加载项目列表失败：' + (e?.message || '请检查后端 /api/projects'))
  }
}

async function loadReports() {
  // R2：报告页跳转 ?test_run_id= 时按任务过滤（无需项目）
  if (!projectId.value && !runFilter.value) return
  loadingReports.value = true
  try {
    const params: any = runFilter.value
      ? { test_run_id: runFilter.value }
      : { project_id: projectId.value }
    const res: any = await coverageApi.list(params)
    const list = res?.data || []
    reports.value = Array.isArray(list) ? list : []
    if (reports.value.length && !reports.value.some((r: any) => r.id === selectedReportId.value)) {
      selectedReportId.value = reports.value[0].id
      latestReportId.value = reports.value[0].id
    } else if (!reports.value.length) {
      selectedReportId.value = ''
      latestReportId.value = ''
    } else {
      latestReportId.value = selectedReportId.value
    }
  } catch {
    reports.value = []
  } finally {
    loadingReports.value = false
  }
}

async function loadDashboard() {
  if (!projectId.value) return
  try {
    const res: any = await coverageApi.dashboard(projectId.value)
    dashboard.value = res?.data || null
    const selected = reports.value.find((r: any) => r.id === selectedReportId.value)
    if (dashboard.value && selected && selected.id !== dashboard.value.latest?.id) {
      dashboard.value = { ...dashboard.value, latest: selected,
        diff_line_rate: null, diff_branch_rate: null }
    }
    if (dashboard.value) {
      dashboard.value.report_count = reports.value.length
      dashboard.value.file_count = selectedReportId.value ? filesTotal.value : 0
    }
  } catch {
    dashboard.value = null
  }
}

async function loadTrend() {
  if (!projectId.value) return
  try {
    const res: any = await coverageApi.trend(projectId.value, 30)
    trend.value = res?.data || { labels: [], line_rate: [], branch_rate: [] }
  } catch {
    trend.value = { labels: [], line_rate: [], branch_rate: [] }
  }
}

async function loadFiles() {
  if (!latestReportId.value) return
  loadingFiles.value = true
  try {
    const res: any = await coverageApi.files(latestReportId.value, {
      sort: fileSort.value,
      order: fileOrder.value,
      page: page.value,
      page_size: pageSize.value,
      q: fileQuery.value || undefined,
    })
    const d = res?.data || {}
    files.value = d.files || []
    filesTotal.value = d.total || 0
    if (dashboard.value) dashboard.value.file_count = filesTotal.value
  } catch {
    files.value = []
    filesTotal.value = 0
  } finally {
    loadingFiles.value = false
  }
}

async function onFileRowClick(row: any) {
  if (!latestReportId.value) return
  drawerTitle.value = row.path
  drawerOpen.value = true
  loadingSource.value = true
  try {
    const res: any = await coverageApi.source(latestReportId.value, row.path)
    sourceData.value = res?.data || null
  } catch (e: any) {
    sourceData.value = null
    ElMessage.error('加载行级数据失败：' + (e?.message || '未知错误'))
  } finally {
    loadingSource.value = false
  }
}

async function onProjectChange() {
  runFilter.value = ''
  selectedReportId.value = ''
  latestReportId.value = ''
  files.value = []
  filesTotal.value = 0
  dashboard.value = null
  trend.value = { labels: [], line_rate: [], branch_rate: [] }
  coverageRuns.value = []
  await loadCoverageRuns()
  await loadReports()
  await loadDashboard()
  await loadTrend()
  await loadFiles()
}

async function onReportChange() {
  latestReportId.value = selectedReportId.value
  page.value = 1
  await loadDashboard()
  await loadFiles()
}

async function refreshAll() {
  await loadCoverageRuns()
  await loadReports()
  await loadDashboard()
  await loadTrend()
  await loadFiles()
}

function openUploadDialog() {
  if (!projectId.value) {
    ElMessage.warning('请先选择项目')
    return
  }
  uploadForm.value = { tool: 'coverage.py', language: '', file: null }
  uploadDialogVisible.value = true
}

function onUploadFileChange(file: any) {
  // el-upload 的 file 对象在 raw
  uploadForm.value.file = file?.raw || null
  if (uploadForm.value.file?.name.toLowerCase().endsWith('.out')) {
    uploadForm.value.tool = 'go_cover'
    uploadForm.value.language = 'go'
  }
}

async function submitUpload() {
  if (!uploadForm.value.file || !uploadForm.value.tool) {
    ElMessage.warning('请选择工具和报告文件')
    return
  }
  uploading.value = true
  try {
    const res: any = await coverageApi.upload(uploadForm.value.file, {
      project_id: projectId.value,
      tool: uploadForm.value.tool,
      language: uploadForm.value.language || undefined,
    })
    const d = res?.data || {}
    ElMessage.success(
      `已入库：${d.tool === 'go_cover' ? '语句' : '行'}覆盖 ${d.line_rate}%（${d.file_count} 个文件）`
    )
    uploadDialogVisible.value = false
    selectedReportId.value = ''
    await refreshAll()
  } catch {
    /* 拦截器已提示 */
  } finally {
    uploading.value = false
  }
}

function onFileQueryChange() {
  page.value = 1
  loadFiles()
}
function onFileSortChange() {
  page.value = 1
  loadFiles()
}
function onPageChange(p: number) {
  page.value = p
  loadFiles()
}
function onPageSizeChange(s: number) {
  pageSize.value = s
  page.value = 1
  loadFiles()
}

async function initCoverageFromRoute() {
  await loadProjects()
  const pid = (route.query.project_id as string) || ''
  const rid = (route.query.test_run_id as string) || ''
  if (pid) {
    projectId.value = pid
    await onProjectChange()
  } else if (rid) {
    runFilter.value = rid
    await showCoverageRun(rid).catch(() => undefined)
    await loadReports()
  } else if (projects.value.length > 0) {
    projectId.value = projects.value[0].id
    await onProjectChange()
  }
}

onMounted(async () => {
  await initCoverageFromRoute()
})

watch(
  () => [route.query.project_id, route.query.test_run_id],
  async () => {
    await initCoverageFromRoute()
  }
)
</script>

<style scoped>
.coverage-dashboard {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.report-meta-bar {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 8px 16px;
  background: var(--app-bg-page);
  border-radius: 6px;
  font-size: 13px;
  color: var(--el-text-color-regular);
  flex-wrap: wrap;
}
.meta-item {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.filter-card .filter-row {
  display: flex;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
}
.filter-item {
  display: flex;
  align-items: center;
  gap: 8px;
}
.filter-item .label {
  color: var(--el-text-color-regular);
  font-size: 13px;
  white-space: nowrap;
}

.metric-row {
  margin: 0;
}
.metric-card {
  text-align: center;
}
.metric-label {
  color: var(--el-text-color-secondary);
  font-size: 13px;
  margin-bottom: 4px;
}
.metric-value {
  font-size: 28px;
  font-weight: 600;
  line-height: 1.2;
}
.metric-value.neutral {
  color: var(--el-text-color-primary);
}
.metric-unit {
  font-size: 14px;
  color: var(--el-text-color-secondary);
  margin-left: 2px;
}
.metric-unit-sm {
  font-size: 14px;
  color: var(--el-text-color-secondary);
  font-weight: normal;
}
.metric-diff {
  margin-top: 8px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  display: flex;
  justify-content: center;
  align-items: center;
  gap: 4px;
}
.metric-diff-label {
  color: var(--el-text-color-secondary);
}

.trend-card :deep(.el-card__body) {
  padding: 12px 16px;
}

.files-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}
.files-tools {
  display: flex;
  gap: 8px;
}
.file-path {
  font-family: 'Consolas', 'Monaco', monospace;
  font-size: 12px;
  color: var(--el-text-color-primary);
}
.rate-good {
  color: var(--el-color-success);
  font-weight: 600;
}
.rate-mid {
  color: var(--el-color-warning);
  font-weight: 600;
}
.rate-bad {
  color: var(--el-color-danger);
  font-weight: 600;
}
.text-muted {
  color: var(--el-text-color-secondary);
}
.files-pagination {
  margin-top: 12px;
  text-align: right;
}

/* 源码抽屉 */
.source-drawer-body {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.source-summary {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 4px;
}
.legend {
  display: flex;
  gap: 16px;
  font-size: 12px;
  color: var(--el-text-color-regular);
  padding: 4px 0;
  border-bottom: 1px solid var(--el-border-color-lighter);
}
.legend-item {
  display: flex;
  align-items: center;
  gap: 4px;
}
.dot {
  display: inline-block;
  width: 10px;
  height: 10px;
  border-radius: 50%;
}
.dot.covered {
  background: var(--el-color-success);
}
.dot.partial {
  background: var(--el-color-warning);
}
.dot.uncovered {
  background: var(--el-color-danger);
}
.source-line-list {
  max-height: calc(100vh - 240px);
  overflow-y: auto;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 4px;
  background: var(--app-table-header-bg);
  font-family: 'Consolas', 'Monaco', monospace;
  font-size: 12px;
}
.source-line {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 2px 12px;
  border-bottom: 1px solid var(--el-fill-color);
}
.source-line .line-no {
  width: 50px;
  text-align: right;
  color: var(--el-text-color-secondary);
}
.source-line .line-icon {
  width: 16px;
  text-align: center;
  font-size: 14px;
}
.source-line .line-hits {
  color: var(--el-text-color-regular);
}
.source-line .line-branch {
  color: var(--el-text-color-secondary);
  font-size: 11px;
}
.source-line.line-covered {
  background: var(--el-color-success-light-9);
}
.source-line.line-covered .line-icon {
  color: var(--el-color-success);
}
.source-line.line-uncovered {
  background: var(--el-color-danger-light-9);
}
.source-line.line-uncovered .line-icon {
  color: var(--el-color-danger);
}
.source-line.line-partial {
  background: var(--el-color-warning-light-9);
}
.source-line.line-partial .line-icon {
  color: var(--el-color-warning);
}
.empty-card {
  padding: 8px;
}
.empty-tip {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  margin-top: 8px;
}
.cov-switch {
  display: flex;
  align-items: center;
  gap: 6px;
}
.cov-switch-label {
  font-size: 13px;
  color: var(--el-text-color-regular);
}
</style>
