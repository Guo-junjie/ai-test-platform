<template>
  <el-dialog
    :model-value="visible"
    :title="dialogTitle"
    width="560px"
    :close-on-click-modal="false"
    @close="handleCancel"
  >
    <el-form
      ref="formRef"
      :model="formData"
      :rules="formRules"
      label-width="120px"
      label-position="right"
    >
      <!-- GitHub 表单 -->
      <template v-if="sourceType === 'github'">
        <el-form-item label="仓库名称" prop="name">
          <el-input v-model="formData.name" placeholder="如：my-project" />
        </el-form-item>
        <el-form-item label="仓库 URL" prop="repo_url">
          <el-input
            v-model="formData.repo_url"
            placeholder="https://github.com/owner/repo"
          />
        </el-form-item>
        <el-form-item label="GitHub Token" prop="github_token">
          <el-input
            v-model="formData.github_token"
            type="password"
            show-password
            :placeholder="isEdit ? '留空则保持原 Token 不变；如需更换请输入新 Token' : 'ghp_xxxxxxxxxxxx'"
          />
        </el-form-item>
        <el-form-item label="分支" prop="branch">
          <el-input v-model="formData.branch" placeholder="main" />
        </el-form-item>
        <el-form-item label="Commit SHA" prop="commit_sha">
          <el-input
            v-model="formData.commit_sha"
            placeholder="可选，指定 commit 版本"
          />
        </el-form-item>
      </template>

      <!-- SVN 表单 -->
      <template v-if="sourceType === 'svn'">
        <el-form-item label="仓库名称" prop="name">
          <el-input v-model="formData.name" placeholder="如：svn-project" />
        </el-form-item>
        <el-form-item label="SVN URL" prop="svn_url">
          <el-input
            v-model="formData.svn_url"
            placeholder="https://svn.example.com/svn/project"
          />
        </el-form-item>
        <el-form-item label="用户名" prop="svn_username">
          <el-input v-model="formData.svn_username" placeholder="SVN 认证用户名" />
        </el-form-item>
        <el-form-item label="密码" prop="svn_password">
          <el-input
            v-model="formData.svn_password"
            type="password"
            show-password
            :placeholder="isEdit ? '留空则保持原密码不变；如需更换请输入新密码' : 'SVN 认证密码'"
          />
        </el-form-item>
        <el-form-item label="修订版本" prop="svn_revision">
          <el-input
            v-model="formData.svn_revision"
            placeholder="可选，指定修订版本号"
          />
        </el-form-item>
      </template>
    </el-form>

    <template #footer>
      <el-button @click="handleCancel">取消</el-button>
      <el-button type="primary" :loading="saving" @click="handleSave">
        保存
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { ref, reactive, computed, watch } from 'vue'
import type { FormInstance, FormRules } from 'element-plus'
import { ElMessage } from 'element-plus'
import { sourceApi } from '@/api'

const props = defineProps<{
  sourceType: 'github' | 'svn'
  visible: boolean
  /** 编辑模式：传入要编辑的 source 行（来自列表）；不传 = 添加模式 */
  editingSource?: any | null
}>()

const emit = defineEmits<{
  (e: 'save'): void
  (e: 'cancel'): void
}>()

const formRef = ref<FormInstance>()
const saving = ref(false)

const isEdit = computed(() => !!props.editingSource)

const dialogTitle = computed(() => {
  const typeLabel = props.sourceType === 'github' ? 'GitHub' : 'SVN'
  return `${isEdit.value ? '编辑' : '添加'}${typeLabel}数据源`
})

interface FormData {
  name: string
  repo_url: string
  github_token: string
  branch: string
  commit_sha: string
  svn_url: string
  svn_username: string
  svn_password: string
  svn_revision: string
}

const formData = reactive<FormData>({
  name: '',
  repo_url: '',
  github_token: '',
  branch: 'main',
  commit_sha: '',
  svn_url: '',
  svn_username: '',
  svn_password: '',
  svn_revision: '',
})

const formRules = computed<FormRules>(() => {
  if (props.sourceType === 'github') {
    return {
      name: [{ required: true, message: '请输入仓库名称', trigger: 'blur' }],
      repo_url: [{ required: true, message: '请输入仓库 URL', trigger: 'blur' }],
      // 编辑模式下 Token 留空 = 保持不变，不强制必填
      github_token: isEdit.value
        ? []
        : [{ required: true, message: '请输入 GitHub Token', trigger: 'blur' }],
    }
  }
  return {
    name: [{ required: true, message: '请输入仓库名称', trigger: 'blur' }],
    svn_url: [{ required: true, message: '请输入 SVN URL', trigger: 'blur' }],
    svn_username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
    // 编辑模式下 SVN 密码留空 = 保持不变，不强制必填
    svn_password: isEdit.value
      ? []
      : [{ required: true, message: '请输入密码', trigger: 'blur' }],
  }
})

// 重置 / 预填表单
watch(
  () => props.visible,
  (val) => {
    if (!val) return
    // 编辑模式：从 editingSource 预填可编辑字段
    // 关键：Token / SVN 密码不回填掩码字符串，留空由后端 merge 逻辑保持原值
    const src = props.editingSource
    const cfg = (src?.config && typeof src.config === 'object') ? src.config : {}
    Object.assign(formData, {
      name: src?.name ?? '',
      repo_url: cfg.repo_url ?? '',
      github_token: '',
      branch: cfg.branch ?? 'main',
      commit_sha: cfg.commit_sha ?? '',
      svn_url: cfg.svn_url ?? '',
      svn_username: cfg.svn_username ?? '',
      svn_password: '',
      svn_revision: cfg.svn_revision ?? '',
    })
    formRef.value?.clearValidate()
  }
)

async function handleSave() {
  if (!formRef.value) return
  await formRef.value.validate(async (valid) => {
    if (!valid) return

    saving.value = true
    try {
      const config: Record<string, string> =
        props.sourceType === 'github'
          ? {
              repo_url: formData.repo_url,
              branch: formData.branch,
              commit_sha: formData.commit_sha,
              // Token 留空 = 后端 merge 保持原 Token；不传这个 key
              ...(formData.github_token.trim()
                ? { github_token: formData.github_token }
                : {}),
            }
          : {
              svn_url: formData.svn_url,
              svn_username: formData.svn_username,
              svn_revision: formData.svn_revision,
              // SVN 密码留空 = 后端 merge 保持原密码；不传这个 key
              ...(formData.svn_password.trim()
                ? { svn_password: formData.svn_password }
                : {}),
            }

      if (isEdit.value && props.editingSource) {
        await sourceApi.update(props.editingSource.id, {
          name: formData.name,
          config,
        })
        ElMessage.success('数据源已更新')
      } else {
        await sourceApi.connect({
          name: formData.name,
          source_type: props.sourceType,
          config,
        })
        ElMessage.success('数据源添加成功')
      }
      emit('save')
    } catch {
      // 错误已由 axios 拦截器处理
    } finally {
      saving.value = false
    }
  })
}

function handleCancel() {
  emit('cancel')
}
</script>
