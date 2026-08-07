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
            placeholder="ghp_xxxxxxxxxxxx"
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
            placeholder="SVN 认证密码"
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
}>()

const emit = defineEmits<{
  (e: 'save'): void
  (e: 'cancel'): void
}>()

const formRef = ref<FormInstance>()
const saving = ref(false)

const dialogTitle = computed(() => {
  const typeLabel = props.sourceType === 'github' ? 'GitHub' : 'SVN'
  return `添加${typeLabel}数据源`
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
      github_token: [{ required: true, message: '请输入 GitHub Token', trigger: 'blur' }],
    }
  }
  return {
    name: [{ required: true, message: '请输入仓库名称', trigger: 'blur' }],
    svn_url: [{ required: true, message: '请输入 SVN URL', trigger: 'blur' }],
    svn_username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
    svn_password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
  }
})

// 重置表单
watch(
  () => props.visible,
  (val) => {
    if (val) {
      Object.assign(formData, {
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
      formRef.value?.clearValidate()
    }
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
              github_token: formData.github_token,
              branch: formData.branch,
              commit_sha: formData.commit_sha,
            }
          : {
              svn_url: formData.svn_url,
              svn_username: formData.svn_username,
              svn_password: formData.svn_password,
              svn_revision: formData.svn_revision,
            }

      await sourceApi.connect({
        name: formData.name,
        source_type: props.sourceType,
        config,
      })

      ElMessage.success('数据源添加成功')
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
