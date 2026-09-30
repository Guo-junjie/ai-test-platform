<template>
  <main class="login-page">
    <section class="brand-panel">
      <div class="brand-content">
        <div class="brand-logo"><el-icon><Promotion /></el-icon><span>AI 测试平台</span></div>
        <h1>AI 自动化测试平台</h1>
        <p>让代码质量，从提交那一刻开始被看见：接口文档解析、智能用例生成、计划化执行、质量门禁卡控形成闭环。</p>
        <ul class="brand-features" aria-label="平台核心能力">
          <li><el-icon><MagicStick /></el-icon><span>智能用例生成</span></li>
          <li><el-icon><TrendCharts /></el-icon><span>质量趋势洞察</span></li>
          <li><el-icon><CircleCheck /></el-icon><span>门禁自动卡控</span></li>
        </ul>
      </div>
    </section>

    <section class="form-panel">
      <div class="form-card">
        <h2>欢迎回来</h2>
        <p class="form-subtitle">请登录后继续使用测试平台</p>

        <el-alert v-if="errorMsg" :title="errorMsg" type="error" show-icon closable class="form-error" @close="errorMsg = ''" />

        <el-form ref="formRef" :model="form" :rules="rules" label-position="top" @submit.prevent="handleLogin">
          <el-form-item label="用户名" prop="username">
            <el-input v-model="form.username" placeholder="请输入用户名" size="large" :prefix-icon="User" clearable autocomplete="username" @keyup.enter="handleLogin" />
          </el-form-item>
          <el-form-item label="密码" prop="password">
            <el-input v-model="form.password" type="password" placeholder="请输入密码" size="large" :prefix-icon="Lock" show-password autocomplete="current-password" @keyup.enter="handleLogin" />
          </el-form-item>
          <div class="login-options">
            <el-checkbox v-model="form.remember">记住我</el-checkbox>
            <button type="button" class="forgot-button" @click="showPasswordHelp">忘记密码？</button>
          </div>
          <el-button native-type="submit" type="primary" size="large" class="submit-button" :loading="loading">
            {{ loading ? '登录中…' : '登 录' }}
          </el-button>
        </el-form>
      </div>
    </section>
  </main>
</template>

<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { CircleCheck, Lock, MagicStick, Promotion, TrendCharts, User } from '@element-plus/icons-vue'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { useAuthStore } from '@/stores'

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()
const formRef = ref<FormInstance>()
const loading = ref(false)
const errorMsg = ref('')
const form = reactive({ username: '', password: '', remember: true })
const rules: FormRules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
}

async function handleLogin(): Promise<void> {
  if (!formRef.value) return
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return
  errorMsg.value = ''
  loading.value = true
  try {
    const success = await authStore.login(form.username, form.password, form.remember)
    if (!success) {
      errorMsg.value = '登录失败，请检查用户名和密码'
      return
    }
    ElMessage.success('登录成功')
    await router.push((route.query.redirect as string) || '/dashboard')
  } catch {
    errorMsg.value = '登录失败，请稍后重试'
  } finally {
    loading.value = false
  }
}

function showPasswordHelp(): void {
  ElMessage.info('请联系系统管理员为你重置密码')
}
</script>

<style scoped>
.login-page { display: grid; grid-template-columns: 1.05fr .95fr; min-height: 100vh; background: #fff; }
.brand-panel { position: relative; overflow: hidden; display: flex; flex-direction: column; justify-content: center; padding: 48px; color: #fff; background: linear-gradient(135deg, #1e4fbc, #2563eb 52%, #6692f1); }
.brand-panel::before, .brand-panel::after { position: absolute; width: 360px; height: 360px; border-radius: 50%; background: rgba(255,255,255,.07); content: ''; pointer-events: none; }
.brand-panel::before { top: -180px; right: -100px; }
.brand-panel::after { right: 15%; bottom: -260px; width: 480px; height: 480px; }
.brand-content { position: relative; z-index: 1; display: flex; flex-direction: column; gap: 22px; width: 100%; max-width: 540px; margin: 0 auto; }
.brand-logo { display: flex; align-items: center; gap: 9px; font-size: 16px; font-weight: 600; }
.brand-logo .el-icon { width: 20px; height: 20px; font-size: 20px; }
.brand-content h1 { margin: 0; font-size: 30px; font-weight: 700; line-height: 1.3; letter-spacing: .5px; }
.brand-content > p { max-width: 420px; margin: 0; font-size: 14px; line-height: 1.75; opacity: .88; }
.brand-features { display: flex; flex-wrap: wrap; gap: 10px; margin: 6px 0 0; padding: 0; list-style: none; }
.brand-features li { display: inline-flex; align-items: center; gap: 7px; padding: 7px 13px; border: 1px solid rgba(255,255,255,.22); border-radius: 999px; background: rgba(255,255,255,.14); font-size: 12.5px; }
.brand-features .el-icon { font-size: 14px; }
.form-panel { display: flex; align-items: center; justify-content: center; padding: 48px 32px; background: var(--app-bg-page); }
.form-card { width: 100%; max-width: 372px; }
.form-card h2 { margin: 0; color: var(--app-text-primary); font-size: 22px; font-weight: 700; }
.form-subtitle { margin: 7px 0 22px; color: var(--app-text-secondary); font-size: 13px; }
.form-error { margin-bottom: 18px; }
.login-options { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin: -2px 0 18px; }
.forgot-button { padding: 0; border: 0; color: var(--app-accent); background: transparent; font: inherit; font-size: 13px; cursor: pointer; }
.forgot-button:hover { color: var(--app-accent-hover); }
.submit-button { width: 100%; height: 40px; font-weight: 600; letter-spacing: 2px; }
:deep(.el-form-item) { margin-bottom: 18px; }
:deep(.el-form-item__label) { padding-bottom: 6px; color: var(--app-text-regular); font-size: 13px; font-weight: 500; line-height: 1.4; }
:deep(.el-checkbox__label) { color: var(--app-text-regular); font-size: 13px; }

@media (max-width: 960px) {
  .login-page { grid-template-columns: 1fr; }
  .brand-panel { min-height: 300px; padding: 40px 24px 34px; }
  .brand-content { gap: 16px; }
  .brand-content h1 { font-size: 26px; }
  .form-panel { padding: 42px 24px 56px; }
}
@media (max-width: 560px) {
  .brand-panel { min-height: 260px; }
  .brand-features { display: none; }
}
</style>
