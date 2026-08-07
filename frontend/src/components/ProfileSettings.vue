<template>
  <div class="profile-settings">
    <el-form
      ref="profileFormRef"
      :model="profile"
      :rules="profileRules"
      label-width="140px"
      style="max-width: 620px;"
      v-loading="profileLoading"
    >
      <el-divider content-position="left">个人信息</el-divider>
      <el-form-item label="用户名" prop="username">
        <el-input v-model="profile.username" placeholder="请输入用户名" />
      </el-form-item>
      <el-form-item label="邮箱" prop="email">
        <el-input v-model="profile.email" placeholder="请输入邮箱" />
      </el-form-item>
      <el-form-item label="当前角色">
        <el-tag>{{ roleLabels[authStore.role] || authStore.role }}</el-tag>
      </el-form-item>
      <el-form-item>
        <el-button type="primary" :loading="savingProfile" @click="saveProfile">
          保存个人信息
        </el-button>
      </el-form-item>
    </el-form>

    <el-form
      ref="pwdFormRef"
      :model="pwdForm"
      :rules="pwdRules"
      label-width="140px"
      style="max-width: 620px;"
    >
      <el-divider content-position="left">修改密码</el-divider>
      <el-form-item label="当前密码" prop="old_password">
        <el-input v-model="pwdForm.old_password" type="password" show-password autocomplete="off" />
      </el-form-item>
      <el-form-item label="新密码" prop="new_password">
        <el-input
          v-model="pwdForm.new_password"
          type="password"
          show-password
          autocomplete="off"
          placeholder="至少 6 位"
        />
      </el-form-item>
      <el-form-item label="确认新密码" prop="confirm_password">
        <el-input
          v-model="pwdForm.confirm_password"
          type="password"
          show-password
          autocomplete="off"
        />
      </el-form-item>
      <el-form-item>
        <el-button type="primary" :loading="savingPwd" @click="changePassword">
          修改密码
        </el-button>
      </el-form-item>
    </el-form>
  </div>
</template>

<script setup lang="ts">
/**
 * 个人设置面板：个人信息修改 + 密码修改。
 *
 * 被 Settings.vue（管理员「系统配置」页的个人设置 Tab）
 * 与 Profile.vue（所有登录用户可访问的 /profile 页）复用。
 */
import { ref, reactive, onMounted } from 'vue'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { authApi } from '@/api'
import { useAuthStore } from '@/stores'

const authStore = useAuthStore()

const profileLoading = ref(false)
const savingProfile = ref(false)
const savingPwd = ref(false)

const profileFormRef = ref<FormInstance>()
const pwdFormRef = ref<FormInstance>()

/** 角色枚举 -> 中文标签 */
const roleLabels: Record<string, string> = {
  admin: '管理员',
  tester: '测试工程师',
  developer: '开发者',
  viewer: '访客',
}

/** 个人信息表单 */
const profile = reactive({
  username: '',
  email: '',
})

/** 修改密码表单 */
const pwdForm = reactive({
  old_password: '',
  new_password: '',
  confirm_password: '',
})

const profileRules: FormRules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  email: [
    { required: true, message: '请输入邮箱', trigger: 'blur' },
    { type: 'email', message: '邮箱格式不正确', trigger: 'blur' },
  ],
}

const pwdRules: FormRules = {
  old_password: [{ required: true, message: '请输入当前密码', trigger: 'blur' }],
  new_password: [
    { required: true, message: '请输入新密码', trigger: 'blur' },
    { min: 6, message: '密码长度至少 6 位', trigger: 'blur' },
  ],
  confirm_password: [
    { required: true, message: '请再次输入新密码', trigger: 'blur' },
    {
      validator: (_rule: any, value: string, callback: (err?: Error) => void) => {
        if (value !== pwdForm.new_password) {
          callback(new Error('两次输入的密码不一致'))
          return
        }
        callback()
      },
      trigger: 'blur',
    },
  ],
}

/** 加载当前登录用户信息，填充个人设置表单 */
async function loadProfile(): Promise<void> {
  profileLoading.value = true
  try {
    const res: any = await authApi.me()
    const d = res?.data ?? res ?? {}
    profile.username = d.username || authStore.user?.username || ''
    profile.email = d.email || authStore.user?.email || ''
  } catch {
    // 接口失败时退化为本地 auth store 中的值
    profile.username = authStore.user?.username || ''
    profile.email = authStore.user?.email || ''
  } finally {
    profileLoading.value = false
  }
}

/** 保存个人信息 */
async function saveProfile(): Promise<void> {
  if (!profileFormRef.value) return
  const valid = await profileFormRef.value.validate().catch(() => false)
  if (!valid) return

  savingProfile.value = true
  try {
    await authApi.updateProfile({ username: profile.username, email: profile.email })
    ElMessage.success('个人信息保存成功')
    // 同步刷新全局用户状态，保证顶栏用户名即时更新
    await authStore.fetchCurrentUser()
  } catch (e: any) {
    ElMessage.error(e?.message || '保存失败')
  } finally {
    savingProfile.value = false
  }
}

/** 修改密码 */
async function changePassword(): Promise<void> {
  if (!pwdFormRef.value) return
  const valid = await pwdFormRef.value.validate().catch(() => false)
  if (!valid) return

  savingPwd.value = true
  try {
    await authApi.changePassword({
      old_password: pwdForm.old_password,
      new_password: pwdForm.new_password,
    })
    ElMessage.success('密码修改成功')
    pwdForm.old_password = ''
    pwdForm.new_password = ''
    pwdForm.confirm_password = ''
    pwdFormRef.value.clearValidate()
  } catch (e: any) {
    ElMessage.error(e?.message || '密码修改失败')
  } finally {
    savingPwd.value = false
  }
}

onMounted(loadProfile)

defineExpose({ loadProfile })
</script>
