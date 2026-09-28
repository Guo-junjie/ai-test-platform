<template>
  <div class="scenario-page">
    <!-- 编排输入区 -->
    <el-card shadow="hover">
      <template #header>AI 编排测试场景</template>
      <el-form label-width="80px">
        <el-form-item label="项目" required>
          <el-select v-model="projectId" placeholder="选择项目" filterable style="width: 260px" @change="onProjectChange">
            <el-option v-for="p in projects" :key="p.id" :label="p.name" :value="p.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="接口">
          <el-select
            v-model="selectedEndpointIds"
            multiple
            filterable
            collapse-tags
            placeholder="不选则按自然语言自动检索"
            style="width: 420px"
            @visible-change="onEndpointVisible"
          >
            <el-option v-for="e in endpoints" :key="e.id" :label="`${e.method} ${e.path}`" :value="e.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="场景描述" required>
          <el-input
            v-model="nlInput"
            type="textarea"
            :rows="4"
            placeholder="用自然语言描述测试场景，例如：用户先登录获取 token，然后创建订单，再用 token 查询订单详情"
          />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="orchestrating" :disabled="!canOrchestrate" @click="orchestrate">AI 编排</el-button>
          <el-button :loading="dryRunning" :disabled="!canOrchestrate" @click="dryRun">生成预览</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- 编排结果 -->
    <el-card v-if="scenario" shadow="hover" style="margin-top: 16px" v-loading="saving || adopting">
      <template #header>
        编排结果
        <el-tag size="small" style="margin-left: 8px">{{ scenario.name }}</el-tag>
        <el-tag size="small" :type="statusType(scenario.status)" style="margin-left: 8px">
          {{ statusLabel(scenario.status) }}
        </el-tag>
        <el-tag v-if="scenario.engine" size="small" :type="scenario.engine === 'ai' ? 'success' : 'info'" style="margin-left: 8px">
          {{ scenario.engine === 'ai' ? 'AI 编排' : '规则兜底' }}
        </el-tag>
        <span class="muted" style="margin-left: 8px">（共 {{ scenario.steps?.length || 0 }} 步）</span>
      </template>

      <!-- 步骤依赖链 -->
      <el-steps :active="(scenario.steps?.length || 0)" align-center finish-status="success" style="margin-bottom: 16px">
        <el-step
          v-for="(step, idx) in scenario.steps"
          :key="idx"
          :title="`步骤 ${step.step_order}`"
          :description="`${step.method} ${step.url}`"
        />
      </el-steps>

      <!-- 步骤明细 -->
      <el-collapse v-model="activeSteps">
        <el-collapse-item v-for="(step, idx) in scenario.steps" :key="idx" :name="idx">
          <template #title>
            <span class="step-title">
              <b>#{{ step.step_order }}</b>
              <span class="method-tag">{{ step.method }}</span>
              <span class="url-text">{{ step.url }}</span>
              <span class="action-desc">{{ step.action_desc }}</span>
            </span>
          </template>
          <div class="step-detail">
            <div><b>动作：</b>{{ step.action_desc || '-' }}</div>
            <div v-if="step.depend_on_step">
              <b>依赖前驱步骤：</b><el-tag size="small" type="warning">#{{ step.depend_on_step }}</el-tag>
            </div>
            <div v-if="step.extract && Object.keys(step.extract).length">
              <b>提取变量：</b>
              <el-tag v-for="(path, key) in step.extract" :key="key" size="small" type="success" style="margin-right: 6px">
                {{ key }} → {{ path }}
              </el-tag>
            </div>
            <div v-if="step.inject && Object.keys(step.inject).length">
              <b>变量去向：</b>
              <el-tag v-for="(target, key) in step.inject" :key="key" size="small" style="margin-right: 6px">
                {{ key }} → {{ target }}
              </el-tag>
            </div>
            <div>
              <b>请求：</b>
              <pre class="json-box">{{ JSON.stringify(step.request || {}, null, 2) }}</pre>
            </div>
          </div>
        </el-collapse-item>
      </el-collapse>

      <div style="margin-top: 16px">
        <el-button type="primary" :loading="saving" @click="save">保存步骤</el-button>
        <el-button type="success" :loading="adopting" :disabled="scenario.status === 'adopted'" @click="adopt">采纳</el-button>
        <el-button @click="editSteps">可视化编辑</el-button>
        <el-select v-model="trialEnvironmentId" placeholder="选择已发布环境" style="width: 210px; margin-left: 8px">
          <el-option v-for="env in publishedEnvironments" :key="env.id" :label="env.name" :value="env.id" />
        </el-select>
        <el-button :loading="trialRunning" :disabled="!trialEnvironmentId" @click="trialRun">真实试运行</el-button>
      </div>
    </el-card>

    <!-- dry-run 预览 -->
    <el-dialog v-model="previewVisible" title="场景预览（dry-run，未接真实 HTTP）" width="760px">
      <el-alert
        :title="`底层引擎：${previewData.source_engine === 'ai' ? 'AI 编排' : '规则兜底'} · ${previewData.note || ''}`"
        type="info"
        :closable="false"
        style="margin-bottom: 12px"
      />
      <el-timeline>
        <el-timeline-item
          v-for="(req, idx) in previewData.preview_requests || []"
          :key="idx"
          :timestamp="`步骤 ${req.step_order} · ${req.method} ${req.url}`"
          placement="top"
        >
          <pre class="json-box">{{ JSON.stringify(req.request, null, 2) }}</pre>
        </el-timeline-item>
      </el-timeline>
      <el-empty v-if="!(previewData.preview_requests || []).length" description="未生成任何请求步骤" />
    </el-dialog>

    <el-dialog v-model="trialVisible" title="场景试运行结果" width="760px">
      <el-alert
        :title="trialData?.result?.passed ? '场景试运行通过' : '场景试运行未通过'"
        :type="trialData?.result?.passed ? 'success' : 'error'"
        :description="`${trialData?.environment?.name || '-'} · 已执行 ${trialData?.result?.executed_steps || 0}/${trialData?.result?.total_steps || 0} 步`"
        :closable="false"
        show-icon
      />
      <el-table :data="trialData?.result?.step_results || []" style="margin-top: 14px">
        <el-table-column prop="step" label="步骤" width="70" />
        <el-table-column label="请求" min-width="250"><template #default="{row}"><span class="method-tag">{{row.method}}</span> {{row.url}}</template></el-table-column>
        <el-table-column label="结果" width="100"><template #default="{row}"><el-tag :type="row.passed?'success':'danger'">{{row.passed?'通过':'失败'}}</el-tag></template></el-table-column>
        <el-table-column prop="status_code" label="状态码" width="90" />
        <el-table-column prop="response_time_ms" label="耗时(ms)" width="100" />
        <el-table-column prop="error_message" label="失败原因" min-width="180" show-overflow-tooltip />
      </el-table>
    </el-dialog>

    <el-drawer v-model="editVisible" title="场景节点属性" size="min(880px, 96vw)" destroy-on-close>
      <div class="flow-canvas"><div class="flow-node start">开始</div><template v-for="(step,index) in editableSteps" :key="index"><span class="flow-line">↓</span><div class="flow-node api"><b>接口调用 {{index+1}}</b><span>{{step.method}} {{step.url}}</span></div><template v-if="step.condition_field"><span class="flow-line">↓</span><div class="flow-node condition"><b>条件判断</b><span>{{step.condition_field}} {{step.condition_operator}} {{step.condition_value}}</span></div></template><span class="flow-line">↓</span><div class="flow-node assertion"><b>断言</b><span>{{step.assertion?.field||'HTTP 状态码'}} {{step.assertion?.operator||'等于'}} {{step.assertion?.expected??200}}</span></div></template><span class="flow-line">↓</span><div class="flow-node end">结束</div></div>
      <el-collapse accordion class="node-editor"><el-collapse-item v-for="(step,index) in editableSteps" :key="index" :name="index" :title="`步骤 ${index+1} · ${step.method} ${step.url}`"><div class="node-grid"><el-form-item label="接口"><el-select v-model="step.endpoint_id" filterable @change="syncEndpoint(step)"><el-option v-for="ep in endpoints" :key="ep.id" :label="`${ep.method} ${ep.path}`" :value="ep.id"/></el-select></el-form-item><el-form-item label="依赖步骤"><el-select v-model="step.depend_on_step" clearable><el-option v-for="n in index" :key="n" :label="`步骤 ${n}`" :value="n"/></el-select></el-form-item><el-form-item label="条件字段"><el-select v-model="step.condition_field" clearable filterable placeholder="无条件判断"><el-option v-for="field in responseFields(step)" :key="field" :label="field" :value="field"/></el-select></el-form-item><el-form-item label="条件"><el-select v-model="step.condition_operator" :disabled="!step.condition_field"><el-option label="等于" value="eq"/><el-option label="不等于" value="neq"/><el-option label="存在" value="exists"/></el-select></el-form-item><el-form-item label="条件值"><el-input v-model="step.condition_value" :disabled="!step.condition_field"/></el-form-item><el-form-item label="断言字段"><el-select v-model="step.assertion.field" filterable @change="assertionFieldChanged(step)"><el-option label="HTTP 状态码" value="$status"/><el-option v-for="field in responseFields(step)" :key="field" :label="field" :value="field"/></el-select></el-form-item><el-form-item label="断言条件"><el-select v-model="step.assertion.operator"><el-option label="等于" value="eq"/><el-option label="包含" value="contains" :disabled="step.assertion.field==='$status'"/><el-option label="存在" value="exists" :disabled="step.assertion.field==='$status'"/></el-select></el-form-item><el-form-item label="期望值"><el-input v-model="step.assertion.expected" :disabled="step.assertion.operator==='exists'"/></el-form-item></div></el-collapse-item></el-collapse>
      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveEditedSteps">保存</el-button>
      </template>
    </el-drawer>

    <!-- 历史场景 -->
    <el-card shadow="hover" style="margin-top: 16px" v-loading="historyLoading">
      <template #header>
        历史场景
        <el-button size="small" style="float: right" @click="loadHistory">刷新</el-button>
      </template>
      <el-table :data="history" size="small" border>
        <el-table-column prop="name" label="名称" min-width="160" show-overflow-tooltip />
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag size="small" :type="statusType(row.status)">{{ statusLabel(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="nl_input" label="场景描述" min-width="240" show-overflow-tooltip />
        <el-table-column label="步数" width="70" align="center">
          <template #default="{ row }">{{ (row.steps || []).length }}</template>
        </el-table-column>
        <el-table-column label="操作" width="160">
          <template #default="{ row }">
            <el-button size="small" text type="primary" @click="loadOne(row)">查看</el-button>
            <el-button size="small" text type="success" :disabled="row.status === 'adopted'" @click="adoptById(row)">采纳</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { scenarioApi, docApi, projectApi, environmentApi } from '@/api'

const projects = ref<any[]>([])
const projectId = ref<string>('')
const endpoints = ref<any[]>([])
const selectedEndpointIds = ref<string[]>([])
const nlInput = ref<string>('')

const orchestrating = ref(false)
const dryRunning = ref(false)
const saving = ref(false)
const adopting = ref(false)
const historyLoading = ref(false)

const scenario = ref<any>(null)
const activeSteps = ref<number[]>([])
const history = ref<any[]>([])

const previewVisible = ref(false)
const previewData = ref<any>({})

const editVisible = ref(false)
const editableSteps = ref<any[]>([])
const environments = ref<any[]>([])
const trialEnvironmentId = ref('')
const trialRunning = ref(false)
const trialVisible = ref(false)
const trialData = ref<any>({})
const publishedEnvironments = computed(() => environments.value.filter(item => item.status === 'published'))

const STATUS_LABELS: Record<string, string> = {
  draft: '草稿',
  orchestrated: '已编排',
  adopted: '已采纳',
}
const STATUS_TYPES: Record<string, any> = {
  draft: 'info',
  orchestrated: 'warning',
  adopted: 'success',
}

function statusLabel(s: string): string {
  return STATUS_LABELS[s] || s || '-'
}
function statusType(s: string): any {
  return STATUS_TYPES[s] || 'info'
}

const canOrchestrate = computed(() => !!projectId.value && !!nlInput.value.trim() && !orchestrating.value)

async function loadProjects() {
  try {
    const res: any = await projectApi.getList()
    const d = res?.data ?? res
    projects.value = Array.isArray(d) ? d : d?.list || d?.items || []
  } catch {
    projects.value = []
  }
}

async function onProjectChange() {
  selectedEndpointIds.value = []
  endpoints.value = []
  scenario.value = null
  trialEnvironmentId.value = ''
  await Promise.all([loadEndpoints(), loadHistory(), loadEnvironments()])
}

async function loadEnvironments() {
  if (!projectId.value) return
  const res: any = await environmentApi.list(projectId.value)
  environments.value = res?.data?.items || res?.data?.list || (Array.isArray(res?.data) ? res.data : [])
  trialEnvironmentId.value = publishedEnvironments.value[0]?.id || ''
}

async function onEndpointVisible(visible: boolean) {
  if (visible) await loadEndpoints()
}

async function loadEndpoints() {
  if (!projectId.value) {
    endpoints.value = []
    return
  }
  try {
    const res: any = await docApi.listEndpoints({
      project_id: projectId.value,
      page: 1,
      page_size: 200,
    })
    endpoints.value = res?.data?.items || []
  } catch {
    endpoints.value = []
  }
}

async function orchestrate() {
  if (!canOrchestrate.value) return
  orchestrating.value = true
  try {
    const payload: any = {
      project_id: projectId.value,
      nl_input: nlInput.value,
    }
    if (selectedEndpointIds.value.length) payload.endpoint_ids = selectedEndpointIds.value
    const res: any = await scenarioApi.create(payload)
    scenario.value = res?.data || {}
    activeSteps.value = (scenario.value.steps || []).map((_: any, i: number) => i)
    ElMessage.success('场景编排完成')
    await loadHistory()
  } catch (e: any) {
    /* 拦截器已提示 */
  } finally {
    orchestrating.value = false
  }
}

async function dryRun() {
  if (!canOrchestrate.value) return
  dryRunning.value = true
  try {
    const payload: any = {
      project_id: projectId.value,
      nl_input: nlInput.value,
    }
    if (selectedEndpointIds.value.length) payload.endpoint_ids = selectedEndpointIds.value
    const res: any = await scenarioApi.dryRun(payload)
    previewData.value = res?.data || {}
    previewVisible.value = true
  } catch (e: any) {
    /* 拦截器已提示 */
  } finally {
    dryRunning.value = false
  }
}

async function save() {
  if (!scenario.value?.id) return
  saving.value = true
  try {
    const payload: any = {
      name: scenario.value.name,
      description: scenario.value.description,
      nl_input: scenario.value.nl_input,
      steps: scenario.value.steps,
    }
    const res: any = await scenarioApi.update(scenario.value.id, payload)
    scenario.value = res?.data || scenario.value
    ElMessage.success('已保存')
  } catch {
    /* ignore */
  } finally {
    saving.value = false
  }
}

async function adopt() {
  if (!scenario.value?.id) return
  adopting.value = true
  try {
    const res: any = await scenarioApi.adopt(scenario.value.id)
    scenario.value = res?.data?.scenario || scenario.value
    ElMessage.success('场景已采纳')
    await loadHistory()
  } catch {
    /* ignore */
  } finally {
    adopting.value = false
  }
}

async function adoptById(row: any) {
  try {
    await scenarioApi.adopt(row.id)
    ElMessage.success('场景已采纳')
    await loadHistory()
  } catch {
    /* ignore */
  }
}

function editSteps() {
  if (!scenario.value?.steps) return
  editableSteps.value = scenario.value.steps.map((step:any)=>({ ...step, condition_field:step.condition?.field||'', condition_operator:step.condition?.operator||'eq', condition_value:step.condition?.value||'', assertion:{ field:step.assertion?.field||'$status', operator:step.assertion?.operator||'eq', expected:step.assertion?.expected??200 } }))
  editVisible.value = true
}

async function trialRun() {
  if (!scenario.value?.id || !trialEnvironmentId.value) return
  trialRunning.value = true
  try {
    const res: any = await scenarioApi.run(scenario.value.id, trialEnvironmentId.value)
    trialData.value = res?.data || {}
    trialVisible.value = true
  } finally {
    trialRunning.value = false
  }
}

function saveEditedSteps() {
  scenario.value.steps = editableSteps.value.map((step:any) => {
    const { condition_field, condition_operator, condition_value, ...persisted } = step
    return {
      ...persisted,
      condition: condition_field
        ? { field: condition_field, operator: condition_operator, value: condition_value }
        : undefined,
    }
  })
  editVisible.value = false
  void save()
}

function syncEndpoint(step:any){const ep=endpoints.value.find(x=>x.id===step.endpoint_id);if(ep){step.method=ep.method;step.url=ep.path}}
function assertionFieldChanged(step:any){if(step.assertion.field==='$status'){step.assertion.operator='eq';if(!step.assertion.expected)step.assertion.expected=200}}
function responseFields(step:any):string[]{const ep=endpoints.value.find(x=>x.id===step.endpoint_id);const schema=ep?.responses?.[0]?.schema||{};const fields=Object.keys(schema.properties||{}).map(k=>`$.${k}`);return fields.length?fields:['$.data','$.message','$.code']}

async function loadHistory() {
  if (!projectId.value) {
    history.value = []
    return
  }
  historyLoading.value = true
  try {
    const res: any = await scenarioApi.list({ project_id: projectId.value, page: 1, page_size: 50 })
    history.value = res?.data?.items || []
  } catch {
    history.value = []
  } finally {
    historyLoading.value = false
  }
}

async function loadOne(row: any) {
  try {
    const res: any = await scenarioApi.get(row.id)
    scenario.value = res?.data || row
    activeSteps.value = (scenario.value.steps || []).map((_: any, i: number) => i)
  } catch {
    /* ignore */
  }
}

// 一旦切换项目重置当前场景
watch(projectId, () => {
  scenario.value = null
})

onMounted(async () => {
  await loadProjects()
})
</script>

<style scoped>
.muted {
  color: var(--el-text-color-secondary);
  font-size: 13px;
  font-weight: normal;
}
.step-title {
  display: flex;
  align-items: center;
  gap: 8px;
}
.method-tag {
  font-weight: 600;
  color: var(--el-color-primary);
}
.url-text {
  font-family: monospace;
  font-size: 12px;
  color: var(--el-text-color-regular);
}
.action-desc {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.step-detail {
  font-size: 13px;
  line-height: 1.9;
}
.json-box {
  background: var(--el-fill-color-light);
  border-radius: 4px;
  padding: 10px;
  font-size: 12px;
  max-height: 240px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-all;
}
.flow-canvas{display:flex;flex-direction:column;align-items:center;padding:20px;margin-bottom:18px;border-radius:10px;background:var(--el-fill-color-lighter)}.flow-node{min-width:230px;padding:10px 14px;border:2px solid var(--el-border-color);border-radius:8px;background:white;text-align:center}.flow-node span{display:block;margin-top:4px;font-size:12px;color:var(--el-text-color-secondary)}.flow-node.start,.flow-node.end{min-width:100px;border-color:var(--el-color-success)}.flow-node.api{border-color:var(--el-color-primary)}.flow-node.condition{border-color:var(--el-color-warning)}.flow-node.assertion{border-color:var(--el-color-success)}.flow-line{height:24px;color:var(--el-text-color-placeholder)}.node-grid{display:grid;grid-template-columns:1fr 1fr;gap:0 12px}.node-grid .el-select{width:100%}@media(max-width:650px){.node-grid{grid-template-columns:1fr}}
</style>
