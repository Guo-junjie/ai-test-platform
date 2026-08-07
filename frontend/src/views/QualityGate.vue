<template>
  <div class="quality-gate-page">
    <el-card shadow="hover">
      <template #header>
        <div class="card-header">
          <span>质量门禁</span>
          <el-select
            v-model="projectId"
            placeholder="选择项目"
            style="width: 220px;"
            @change="loadConfig"
          >
            <el-option
              v-for="p in projects"
              :key="p.id"
              :label="p.name || p.id"
              :value="p.id"
            />
          </el-select>
        </div>
      </template>

      <el-alert
        title="质量门禁（Quality Gate）"
        description="定义上线通过标准，测试任务完成后自动评估是否达标。不达标时阻断上线流程并发送告警通知。"
        type="warning"
        :closable="false"
        style="margin-bottom: 16px;"
      />

      <el-tabs v-model="activeTab" @tab-change="handleTabChange">
        <!-- 配置 Tab -->
        <el-tab-pane label="门禁规则" name="config">
          <el-form label-width="200px" style="max-width: 700px;" v-loading="configLoading">
            <el-form-item label="启用质量门禁">
              <el-switch v-model="form.enabled" />
            </el-form-item>
            <el-form-item label="阻断上线">
              <el-switch v-model="form.block_deployment" />
            </el-form-item>
            <el-form-item label="失败时通知">
              <el-switch v-model="form.notify_on_fail" />
            </el-form-item>
            <el-divider content-position="left">通过标准</el-divider>
            <el-form-item label="P0 缺陷数上限">
              <el-input-number :min="0" v-model="form.rules.max_p0_defects" />
              <span style="margin-left: 8px; color: #909399;">个</span>
            </el-form-item>
            <el-form-item label="P1 缺陷数上限">
              <el-input-number :min="0" v-model="form.rules.max_p1_defects" />
              <span style="margin-left: 8px; color: #909399;">个</span>
            </el-form-item>
            <el-form-item label="接口测试通过率最低值">
              <el-input-number :min="0" :max="100" v-model="form.rules.min_api_pass_rate" />
              <span style="margin-left: 8px; color: #909399;">%</span>
            </el-form-item>
            <el-form-item label="性能测试通过率最低值">
              <el-input-number :min="0" :max="100" v-model="form.rules.min_perf_pass_rate" />
              <span style="margin-left: 8px; color: #909399;">%</span>
            </el-form-item>
            <el-form-item label="集成测试通过率最低值">
              <el-input-number :min="0" :max="100" v-model="form.rules.min_integration_pass_rate" />
              <span style="margin-left: 8px; color: #909399;">%</span>
            </el-form-item>
            <el-form-item label="质量评分最低值">
              <el-input-number :min="0" :max="100" v-model="form.rules.min_quality_score" />
            </el-form-item>
            <el-form-item>
              <el-button type="primary" :loading="saving" @click="saveConfig">保存门禁规则</el-button>
            </el-form-item>
          </el-form>
        </el-tab-pane>

        <!-- 历史 Tab -->
        <el-tab-pane label="评估历史" name="history">
          <el-table :data="history" v-loading="historyLoading" style="width: 100%">
            <el-table-column prop="created_at" label="时间" width="180" />
            <el-table-column prop="quality_score" label="质量分" width="100">
              <template #default="{ row }">
                <el-tag :type="row.quality_score >= 80 ? 'success' : row.quality_score >= 60 ? 'warning' : 'danger'" size="small">
                  {{ row.quality_score }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="gate_passed" label="门禁结果" width="120">
              <template #default="{ row }">
                <el-tag :type="row.gate_passed ? 'success' : 'danger'" size="small">
                  {{ row.gate_passed ? '通过' : '未通过' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="run_status" label="运行状态" width="120" />
            <el-table-column prop="source_ref" label="来源" min-width="150" show-overflow-tooltip />
            <el-table-column label="违规项" min-width="200">
              <template #default="{ row }">
                <span v-if="row.gate_details?.violations?.length">
                  {{ row.gate_details.violations.length }} 项
                </span>
                <span v-else style="color: #67c23a;">无</span>
              </template>
            </el-table-column>
          </el-table>
          <el-pagination
            v-if="historyTotal > pageSize"
            background
            layout="prev, pager, next, total"
            :total="historyTotal"
            :page-size="pageSize"
            v-model:current-page="page"
            @current-change="loadHistory"
            style="margin-top: 16px; justify-content: flex-end;"
          />
        </el-tab-pane>
      </el-tabs>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { qualityGateApi, projectApi } from '@/api'

const activeTab = ref('config')
const projectId = ref('')
const projects = ref<any[]>([])
const configLoading = ref(false)
const saving = ref(false)
const historyLoading = ref(false)
const history = ref<any[]>([])
const historyTotal = ref(0)
const page = ref(1)
const pageSize = ref(20)

const form = reactive({
  enabled: true,
  block_deployment: true,
  notify_on_fail: true,
  rules: {
    max_p0_defects: 0,
    max_p1_defects: 0,
    min_api_pass_rate: 90,
    min_perf_pass_rate: 80,
    min_integration_pass_rate: 85,
    min_quality_score: 70,
  },
})

/**
 * 从后端加载真实项目列表。
 *
 * 说明：原实现硬编码了 `demo-project` 这个非 UUID 的假 ID，
 * 导致 `GET /api/quality-gate/config/demo-project` 因参数校验失败返回 400。
 * 现改为调用 `GET /api/projects`，projectId 始终是后端返回的真实 UUID。
 */
async function loadProjects(): Promise<void> {
  try {
    const res: any = await projectApi.getList()
    const d = res?.data ?? res ?? {}
    const list = Array.isArray(d) ? d : d.list || d.items || d.projects || []
    projects.value = list
    projectId.value = list[0]?.id || ''
  } catch {
    projects.value = []
    projectId.value = ''
  }
}

async function loadConfig() {
  if (!projectId.value) return
  configLoading.value = true
  try {
    const res: any = await qualityGateApi.getConfig(projectId.value)
    const d = res.data || {}
    form.enabled = d.enabled ?? true
    form.block_deployment = d.block_deployment ?? true
    form.notify_on_fail = d.notify_on_fail ?? true
    const rules = d.rules || {}
    Object.assign(form.rules, {
      max_p0_defects: rules.max_p0_defects ?? 0,
      max_p1_defects: rules.max_p1_defects ?? 0,
      min_api_pass_rate: rules.min_api_pass_rate ?? 90,
      min_perf_pass_rate: rules.min_perf_pass_rate ?? 80,
      min_integration_pass_rate: rules.min_integration_pass_rate ?? 85,
      min_quality_score: rules.min_quality_score ?? 70,
    })
  } catch (e: any) {
    ElMessage.warning(e?.message || '加载门禁配置失败，使用默认值')
  } finally {
    configLoading.value = false
  }
}

async function saveConfig() {
  if (!projectId.value) {
    ElMessage.warning('请先选择项目')
    return
  }
  saving.value = true
  try {
    await qualityGateApi.updateConfig(projectId.value, {
      enabled: form.enabled,
      block_deployment: form.block_deployment,
      notify_on_fail: form.notify_on_fail,
      rules: form.rules,
    })
    ElMessage.success('门禁规则保存成功')
  } catch (e: any) {
    ElMessage.error(e?.message || '保存失败')
  } finally {
    saving.value = false
  }
}

async function loadHistory() {
  if (!projectId.value) return
  historyLoading.value = true
  try {
    const res: any = await qualityGateApi.getHistory(projectId.value, {
      page: page.value,
      page_size: pageSize.value,
    })
    history.value = res.data?.list || []
    historyTotal.value = res.data?.total || 0
  } catch {
    history.value = []
  } finally {
    historyLoading.value = false
  }
}

function handleTabChange(name: string | number) {
  if (name === 'history') loadHistory()
}

onMounted(async () => {
  // 必须先拿到真实 projectId，再加载门禁配置，避免用空/假 ID 请求后端
  await loadProjects()
  if (projectId.value) {
    await loadConfig()
  } else {
    ElMessage.warning('暂无可用项目，请先创建项目后再配置质量门禁')
  }
})
</script>

<style scoped>
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
</style>
