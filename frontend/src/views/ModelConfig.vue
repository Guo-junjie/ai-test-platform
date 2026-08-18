<template>
  <div class="model-config-page">
    <el-card shadow="hover">
      <template #header>
        <div class="card-header">
          <span>AI 模型配置</span>
          <el-button type="primary" @click="openCreateDialog">
            <el-icon><Plus /></el-icon>
            添加模型配置
          </el-button>
        </div>
      </template>
      <el-alert
        title="企业级可配置 AI 模型管理"
        description="支持 OpenAI / Azure OpenAI / 私有部署 vLLM / Ollama / 国产模型（通义千问/文心一言/DeepSeek）等任意 OpenAI 兼容 API。按使用场景（代码解析/用例生成/缺陷分析/修复建议）分配不同模型。"
        type="info"
        :closable="false"
        style="margin-bottom: 16px;"
      />
      <el-table :data="modelConfigs" v-loading="listLoading" style="width: 100%">
        <el-table-column prop="name" label="名称" />
        <el-table-column prop="provider" label="提供商" width="120" />
        <el-table-column prop="model_name" label="模型" width="200" />
        <el-table-column prop="api_base_url" label="API 地址" show-overflow-tooltip />
        <el-table-column label="使用场景" width="200">
          <template #default="{ row }">
            <el-tag v-for="uc in row.use_cases" :key="uc" size="small" style="margin-right: 4px;">
              {{ useCaseLabels[uc] || uc }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="row.is_active ? 'success' : 'info'">
              {{ row.is_active ? '启用' : '禁用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="220">
          <template #default="{ row }">
            <el-button
              size="small"
              type="primary"
              plain
              :loading="testingId === row.id"
              @click="testConnection(row)"
            >
              测试
            </el-button>
            <el-button size="small" plain @click="openEditDialog(row)">编辑</el-button>
            <el-button size="small" type="danger" plain @click="handleDelete(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-card shadow="hover" style="margin-top: 20px;">
      <template #header>模型路由配置</template>
      <el-form label-width="150px" style="max-width: 600px;" v-loading="routingLoading">
        <el-form-item v-for="item in routingFields" :key="item.key" :label="item.label">
          <el-select
            v-model="routingForm[item.key]"
            placeholder="选择模型"
            clearable
            style="width: 100%"
          >
            <el-option
              v-for="cfg in modelConfigs"
              :key="cfg.id"
              :label="cfg.name"
              :value="cfg.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="savingRouting" @click="saveRouting">
            保存路由配置
          </el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- 新建 / 编辑 模型配置对话框 -->
    <el-dialog
      v-model="dialogVisible"
      :title="isEdit ? '编辑模型配置' : '添加模型配置'"
      width="640px"
      destroy-on-close
    >
      <el-form ref="formRef" :model="form" :rules="formRules" label-width="130px">
        <el-form-item label="配置名称" prop="name">
          <el-input v-model="form.name" placeholder="例如：生产环境 GPT-4o" />
        </el-form-item>
        <el-form-item label="提供商" prop="provider">
          <el-select v-model="form.provider" placeholder="选择提供商" style="width: 100%;">
            <el-option
              v-for="p in providerOptions"
              :key="p.value"
              :label="p.label"
              :value="p.value"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="模型名称" prop="model_name">
          <el-input v-model="form.model_name" placeholder="例如：gpt-4o / qwen-max / deepseek-chat" />
        </el-form-item>
        <el-form-item label="API 地址" prop="api_base_url">
          <el-input v-model="form.api_base_url" placeholder="https://api.openai.com/v1" />
        </el-form-item>
        <el-form-item label="API Key" prop="api_key">
          <el-input
            v-model="form.api_key"
            type="password"
            show-password
            :placeholder="isEdit ? '留空表示不修改' : 'sk-...'"
          />
        </el-form-item>
        <el-form-item label="API 版本">
          <el-input v-model="form.api_version" placeholder="Azure OpenAI 需填写，例如 2024-02-01" />
        </el-form-item>
        <el-form-item label="最大 Token 数">
          <el-input-number v-model="form.max_tokens" :min="1" :max="1000000" :step="512" />
        </el-form-item>
        <el-form-item label="温度">
          <el-input-number v-model="form.temperature" :min="0" :max="2" :step="0.1" :precision="2" />
        </el-form-item>
        <el-form-item label="超时(秒)">
          <el-input-number v-model="form.timeout" :min="1" :max="3600" />
        </el-form-item>
        <el-form-item label="最大重试次数">
          <el-input-number v-model="form.max_retries" :min="0" :max="10" />
        </el-form-item>
        <el-form-item label="使用场景">
          <el-select
            v-model="form.use_cases"
            multiple
            placeholder="选择该模型负责的场景"
            style="width: 100%;"
          >
            <el-option
              v-for="(label, value) in useCaseLabels"
              :key="value"
              :label="label"
              :value="value"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="设为默认">
          <el-switch v-model="form.is_default" />
        </el-form-item>
        <el-form-item label="设为备用">
          <el-switch v-model="form.is_fallback" />
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="form.is_active" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submitForm">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from 'element-plus'
import { modelApi } from '@/api'

/** 使用场景枚举 -> 中文标签 */
const useCaseLabels: Record<string, string> = {
  code_analysis: '代码解析',
  case_generation: '用例生成',
  defect_analysis: '缺陷分析',
  fix_suggestion: '修复建议',
  doc_parse: '文档解析',
  doc_review: '文档评审',
  scenario_orchestration: '场景编排',
}

/** 提供商下拉选项 */
const providerOptions = [
  { value: 'OPENAI', label: 'OpenAI / 兼容 API' },
  { value: 'ANTHROPIC', label: 'Anthropic' },
  { value: 'CUSTOM', label: '自定义（Azure/国产模型）' },
  { value: 'LOCAL', label: '本地部署（vLLM/Ollama）' },
]

/** 模型路由字段定义 */
const routingFields = [
  { key: 'code_analysis_model_id', label: '代码解析模型' },
  { key: 'case_generation_model_id', label: '用例生成模型' },
  { key: 'defect_analysis_model_id', label: '缺陷分析模型' },
  { key: 'fix_suggestion_model_id', label: '修复建议模型' },
  { key: 'doc_parse_model_id', label: '文档解析模型' },
  { key: 'doc_review_model_id', label: '文档评审模型' },
  { key: 'scenario_orchestration_model_id', label: '场景编排模型' },
  { key: 'fallback_model_id', label: '备用模型' },
] as const

const modelConfigs = ref<any[]>([])
const listLoading = ref(false)
const routingLoading = ref(false)
const savingRouting = ref(false)
const submitting = ref(false)
const testingId = ref<string>('')

const dialogVisible = ref(false)
const isEdit = ref(false)
const currentId = ref<string>('')
const formRef = ref<FormInstance>()

/** 路由配置表单，key 为 7 个路由字段 */
const routingForm = reactive<Record<string, string>>({
  code_analysis_model_id: '',
  case_generation_model_id: '',
  defect_analysis_model_id: '',
  fix_suggestion_model_id: '',
  doc_parse_model_id: '',
  doc_review_model_id: '',
  scenario_orchestration_model_id: '',
  fallback_model_id: '',
})

/** 模型配置表单默认值 */
function defaultForm() {
  return {
    name: '',
    provider: 'OPENAI',
    model_name: '',
    api_base_url: '',
    api_key: '',
    api_version: '',
    max_tokens: 4096,
    temperature: 0.7,
    timeout: 60,
    max_retries: 3,
    use_cases: [] as string[],
    is_default: false,
    is_fallback: false,
    is_active: true,
  }
}

const form = reactive(defaultForm())

const formRules: FormRules = {
  name: [{ required: true, message: '请输入配置名称', trigger: 'blur' }],
  provider: [{ required: true, message: '请选择提供商', trigger: 'change' }],
  model_name: [{ required: true, message: '请输入模型名称', trigger: 'blur' }],
  api_base_url: [{ required: true, message: '请输入 API 地址', trigger: 'blur' }],
}

/** 兼容后端返回 {code,data} 或裸数组 / {configs:[]} 的多种形态 */
function pickList(res: any): any[] {
  if (Array.isArray(res)) return res
  const d = res?.data ?? res
  if (Array.isArray(d)) return d
  return d?.list || d?.items || d?.configs || []
}

/** 加载模型配置列表 */
async function loadConfigs(): Promise<void> {
  listLoading.value = true
  try {
    const res: any = await modelApi.listConfigs()
    modelConfigs.value = pickList(res)
  } catch {
    modelConfigs.value = []
  } finally {
    listLoading.value = false
  }
}

/** 加载模型路由配置 */
async function loadRouting(): Promise<void> {
  routingLoading.value = true
  try {
    const res: any = await modelApi.getRouting()
    const d = res?.data ?? res ?? {}
    routingFields.forEach((f) => {
      routingForm[f.key] = d[f.key] || ''
    })
  } catch {
    /* 路由未配置时保持默认空值 */
  } finally {
    routingLoading.value = false
  }
}

/** 保存模型路由配置 */
async function saveRouting(): Promise<void> {
  savingRouting.value = true
  try {
    const payload: Record<string, string | null> = {}
    routingFields.forEach((f) => {
      payload[f.key] = routingForm[f.key] || null
    })
    await modelApi.updateRouting(payload)
    ElMessage.success('路由配置保存成功')
  } catch (e: any) {
    ElMessage.error(e?.message || '保存失败')
  } finally {
    savingRouting.value = false
  }
}

/** 打开「新建」对话框 */
function openCreateDialog(): void {
  isEdit.value = false
  currentId.value = ''
  Object.assign(form, defaultForm())
  dialogVisible.value = true
}

/** 打开「编辑」对话框并回填数据 */
function openEditDialog(row: any): void {
  isEdit.value = true
  currentId.value = row.id
  Object.assign(form, defaultForm(), {
    name: row.name || '',
    provider: row.provider || 'OPENAI',
    model_name: row.model_name || '',
    api_base_url: row.api_base_url || '',
    api_key: '', // 出于安全考虑不回填密钥，留空表示不修改
    api_version: row.api_version || '',
    max_tokens: row.max_tokens ?? 4096,
    temperature: row.temperature ?? 0.7,
    timeout: row.timeout ?? 60,
    max_retries: row.max_retries ?? 3,
    use_cases: Array.isArray(row.use_cases) ? [...row.use_cases] : [],
    is_default: !!row.is_default,
    is_fallback: !!row.is_fallback,
    is_active: row.is_active !== false,
  })
  dialogVisible.value = true
}

/** 提交新建 / 编辑表单 */
async function submitForm(): Promise<void> {
  if (!formRef.value) return
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return

  submitting.value = true
  try {
    const payload: Record<string, any> = { ...form }
    // 编辑时 api_key 留空表示保持原值，不提交
    if (isEdit.value && !payload.api_key) {
      delete payload.api_key
    }
    if (isEdit.value) {
      await modelApi.updateConfig(currentId.value, payload)
      ElMessage.success('模型配置更新成功')
    } else {
      await modelApi.createConfig(payload)
      ElMessage.success('模型配置创建成功')
    }
    dialogVisible.value = false
    await loadConfigs()
  } catch (e: any) {
    ElMessage.error(e?.message || '保存失败')
  } finally {
    submitting.value = false
  }
}

/** 测试模型连通性 */
async function testConnection(row: any): Promise<void> {
  testingId.value = row.id
  try {
    const res: any = await modelApi.testConnection(row.id)
    const d = res?.data ?? res ?? {}
    if (d.success === false) {
      ElMessage.error(`连接失败：${d.error || d.message || '未知错误'}`)
    } else {
      const latency = d.latency_ms ? `（${d.latency_ms}ms）` : ''
      ElMessage.success(`连接成功${latency}`)
    }
  } catch (e: any) {
    ElMessage.error(e?.message || '连接测试失败')
  } finally {
    testingId.value = ''
  }
}

/** 删除模型配置（二次确认） */
async function handleDelete(row: any): Promise<void> {
  try {
    await ElMessageBox.confirm(
      `确认删除模型配置「${row.name}」吗？该操作不可恢复。`,
      '删除确认',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }
    )
  } catch {
    return // 用户取消
  }

  try {
    await modelApi.deleteConfig(row.id)
    ElMessage.success('删除成功')
    await loadConfigs()
  } catch (e: any) {
    ElMessage.error(e?.message || '删除失败')
  }
}

onMounted(async () => {
  await loadConfigs()
  await loadRouting()
})
</script>

<style scoped>
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
</style>
