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
        <el-input v-model="profile.username" disabled />
      </el-form-item>
      <el-form-item label="邮箱" prop="email">
        <el-input v-model="profile.email" placeholder="请输入邮箱" />
      </el-form-item>
      <el-form-item label="当前角色">
        <el-tag :type="roleTagType(authStore.role)">{{ roleLabel(authStore.role) }}</el-tag>
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

    <el-divider content-position="left">API Token</el-divider>
    <div class="token-head"><p>用于 CI/CD 或外部工具调用平台 API。Token 明文只在创建时展示一次。</p><el-button type="primary" @click="tokenDialog=true">生成 Token</el-button></div>
    <el-table :data="tokens" v-loading="tokensLoading" style="max-width:900px"><el-table-column prop="name" label="名称" min-width="160"/><el-table-column label="Token" width="150"><template #default="{row}"><code>{{row.prefix}}••••••••</code></template></el-table-column><el-table-column label="最近使用" min-width="170"><template #default="{row}">{{formatTime(row.last_used_at)}}</template></el-table-column><el-table-column label="过期时间" min-width="170"><template #default="{row}">{{formatTime(row.expires_at)}}</template></el-table-column><el-table-column label="状态" width="90"><template #default="{row}"><el-tag :type="row.revoked_at?'info':'success'">{{row.revoked_at?'已吊销':'有效'}}</el-tag></template></el-table-column><el-table-column label="操作" width="90"><template #default="{row}"><el-button text type="danger" :disabled="!!row.revoked_at" @click="revokeToken(row)">吊销</el-button></template></el-table-column></el-table>
    <el-empty v-if="!tokensLoading&&!tokens.length" description="尚未生成 API Token" :image-size="60"/>
    <el-dialog v-model="tokenDialog" title="生成 API Token" width="500px"><template v-if="!createdToken"><el-form label-position="top"><el-form-item label="Token 名称" required><el-input v-model="tokenForm.name" placeholder="例如：Jenkins 发布流水线"/></el-form-item><el-form-item label="有效期"><el-select v-model="tokenForm.expires_in_days"><el-option label="30 天" :value="30"/><el-option label="90 天" :value="90"/><el-option label="1 年" :value="365"/></el-select></el-form-item></el-form></template><template v-else><el-alert type="warning" :closable="false" show-icon title="请立即复制，关闭窗口后无法再次查看明文"/><div class="created-token"><code>{{createdToken}}</code><el-button type="primary" @click="copyToken">复制</el-button></div></template><template #footer><el-button @click="closeTokenDialog">关闭</el-button><el-button v-if="!createdToken" type="primary" :loading="creatingToken" @click="createToken">生成</el-button></template></el-dialog>
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
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from 'element-plus'
import { authApi } from '@/api'
import { useAuthStore } from '@/stores'
import { roleLabel, roleTagType } from '@/utils/roles'

const authStore = useAuthStore()

const profileLoading = ref(false)
const savingProfile = ref(false)
const savingPwd = ref(false)
const tokensLoading = ref(false), tokens = ref<any[]>([]), tokenDialog = ref(false), creatingToken = ref(false), createdToken = ref('')
const tokenForm = reactive({ name: '', expires_in_days: 90 })

const profileFormRef = ref<FormInstance>()
const pwdFormRef = ref<FormInstance>()

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

function formatTime(value?: string): string { return value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '从未' }
async function loadTokens(): Promise<void> { tokensLoading.value = true; try { const res: any = await authApi.listTokens(); tokens.value = res?.data?.items || [] } finally { tokensLoading.value = false } }
async function createToken(): Promise<void> { if (!tokenForm.name.trim()) { ElMessage.warning('请填写 Token 名称'); return } creatingToken.value = true; try { const res: any = await authApi.createToken(tokenForm); createdToken.value = res?.data?.token || ''; await loadTokens() } finally { creatingToken.value = false } }
async function copyToken(): Promise<void> { await navigator.clipboard.writeText(createdToken.value); ElMessage.success('Token 已复制') }
function closeTokenDialog(): void { tokenDialog.value = false; createdToken.value = ''; tokenForm.name = '' }
async function revokeToken(row: any): Promise<void> { try { await ElMessageBox.confirm(`确认吊销「${row.name}」？吊销后使用它的集成会立即失效。`, '吊销 Token', { type: 'warning' }) } catch { return } await authApi.revokeToken(row.id); ElMessage.success('Token 已吊销'); await loadTokens() }

onMounted(() => Promise.all([loadProfile(), loadTokens()]))

defineExpose({ loadProfile })
</script>
<style scoped>
.token-head{display:flex;align-items:center;justify-content:space-between;gap:16px;max-width:900px;margin-bottom:12px}.token-head p{margin:0;color:var(--el-text-color-secondary);font-size:13px}.created-token{display:flex;align-items:center;gap:10px;margin-top:16px;padding:12px;background:var(--el-fill-color-light);border-radius:7px}.created-token code{flex:1;word-break:break-all}.el-dialog .el-select{width:100%}@media(max-width:600px){.token-head{align-items:flex-start;flex-direction:column}}
</style>
