<template>
  <div class="script-panel-page">
    <el-card shadow="hover">
      <template #header>
        <div class="card-header">
          <span>脚本生成</span>
        </div>
      </template>

      <el-form label-width="120px" style="max-width: 900px;">
        <el-form-item label="项目">
          <el-select v-model="projectId" placeholder="选择项目" filterable style="width: 100%;" @change="loadCases">
            <el-option v-for="p in projects" :key="p.id" :label="p.name" :value="p.id" />
          </el-select>
        </el-form-item>

        <el-form-item label="脚本类型">
          <el-radio-group v-model="scriptType">
            <el-radio-button value="pre_script">前置脚本</el-radio-button>
            <el-radio-button value="post_script">后置脚本</el-radio-button>
            <el-radio-button value="sql_script">SQL 脚本</el-radio-button>
          </el-radio-group>
        </el-form-item>

        <el-form-item label="关联用例">
          <el-select v-model="caseId" placeholder="选择要绑定的用例（可选）" clearable filterable style="width: 100%;">
            <el-option v-for="c in cases" :key="c.id" :label="c.title" :value="c.id" />
          </el-select>
        </el-form-item>

        <el-form-item label="需求描述">
          <el-input
            v-model="nlInput"
            type="textarea"
            :rows="4"
            placeholder="用自然语言描述你要生成的脚本，例如：'生成一个前置脚本，准备测试用户数据并初始化环境'"
          />
        </el-form-item>

        <el-form-item label="上下文 JSON">
          <el-input
            v-model="contextJson"
            type="textarea"
            :rows="4"
            placeholder='可选，例如：{"api_info": {"path": "/api/users", "http_method": "POST"}}'
          />
        </el-form-item>

        <el-form-item>
          <el-button type="primary" :loading="generating" @click="handleGenerate">
            <el-icon style="margin-right: 4px;"><MagicStick /></el-icon>
            生成脚本
          </el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <el-card v-if="result" shadow="hover" style="margin-top: 20px;">
      <template #header>
        <div class="card-header">
          <span>生成结果</span>
          <div>
            <el-tag :type="result.syntax_valid ? 'success' : 'danger'" style="margin-right: 8px;">
              {{ result.syntax_valid ? '语法校验通过' : '语法校验失败' }}
            </el-tag>
            <el-button size="small" @click="copyScript">复制</el-button>
          </div>
        </div>
      </template>

      <pre class="code-block"><code>{{ result.script }}</code></pre>

      <el-alert
        v-if="result.safety_check && !result.safety_check.passed"
        title="SQL 安全检查未通过"
        :description="result.safety_check.error || '存在违规的 SQL 语句'"
        type="warning"
        :closable="false"
        style="margin-top: 12px;"
      />
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { scriptsApi, projectApi, caseApi } from '@/api'

const projectId = ref('')
const scriptType = ref('pre_script')
const nlInput = ref('')
const contextJson = ref('')
const caseId = ref('')
const projects = ref<any[]>([])
const cases = ref<any[]>([])
const generating = ref(false)
const result = ref<any>(null)

async function loadProjects(): Promise<void> {
  try {
    const res: any = await projectApi.getList()
    projects.value = Array.isArray(res?.data) ? res.data : (res?.data?.items || res?.data?.list || [])
  } catch {
    projects.value = []
  }
}

async function loadCases(): Promise<void> {
  if (!projectId.value) {
    cases.value = []
    return
  }
  try {
    const res: any = await caseApi.list({ project_id: projectId.value, page_size: 100 })
    cases.value = res?.data?.items || res?.data || []
  } catch {
    cases.value = []
  }
}

async function handleGenerate(): Promise<void> {
  if (!projectId.value) {
    ElMessage.warning('请先选择项目')
    return
  }
  if (!nlInput.value.trim()) {
    ElMessage.warning('请输入需求描述')
    return
  }

  let context: Record<string, any> = {}
  if (contextJson.value.trim()) {
    try {
      context = JSON.parse(contextJson.value)
    } catch {
      ElMessage.error('上下文 JSON 格式错误')
      return
    }
  }

  generating.value = true
  result.value = null
  try {
    const res: any = await scriptsApi.generateScript({
      project_id: projectId.value,
      script_type: scriptType.value,
      nl_input: nlInput.value,
      context,
      case_id: caseId.value || null,
    })
    result.value = res?.data ?? res
    ElMessage.success('脚本生成成功')
  } catch (e: any) {
    ElMessage.error(e?.message || '生成失败')
  } finally {
    generating.value = false
  }
}

async function copyScript(): Promise<void> {
  if (!result.value?.script) return
  try {
    await navigator.clipboard.writeText(result.value.script)
    ElMessage.success('已复制到剪贴板')
  } catch {
    ElMessage.error('复制失败')
  }
}

onMounted(() => {
  loadProjects()
})
</script>

<style scoped>
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.code-block {
  background-color: #282c34;
  color: #abb2bf;
  padding: 16px;
  border-radius: 6px;
  overflow-x: auto;
  font-size: 13px;
  line-height: 1.6;
  max-height: 500px;
  overflow-y: auto;
  margin: 0;
}
</style>
