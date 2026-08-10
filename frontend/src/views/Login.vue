<template>
  <div class="login-page">
    <!-- 左侧：品牌 / 动效面板 -->
    <section class="brand-panel">
      <div class="brand-bg" aria-hidden="true">
        <span class="blob blob-a"></span>
        <span class="blob blob-b"></span>
        <span class="blob blob-c"></span>
      </div>

      <div class="brand-content">
        <div class="brand-logo">
          <el-icon size="26"><Monitor /></el-icon>
          <span>AI Test Platform</span>
        </div>

        <!-- Lottie 动画容器 -->
        <div ref="lottieRef" class="lottie-stage" aria-hidden="true"></div>

        <div class="brand-text">
          <h1 class="brand-title">AI 自动化测试平台</h1>
          <p class="brand-subtitle">让代码质量，从提交那一刻开始被看见</p>
        </div>

        <ul class="brand-features">
          <li><el-icon><Cpu /></el-icon><span>智能用例生成</span></li>
          <li><el-icon><TrendCharts /></el-icon><span>质量趋势洞察</span></li>
          <li><el-icon><CircleCheck /></el-icon><span>门禁自动卡控</span></li>
        </ul>
      </div>
    </section>

    <!-- 右侧：登录表单 -->
    <section class="form-panel">
      <div class="form-card">
        <div class="form-head">
          <h2 class="form-title">欢迎回来</h2>
          <p class="form-desc">请登录后继续使用测试平台</p>
        </div>

        <el-alert
          v-if="errorMsg"
          :title="errorMsg"
          type="error"
          show-icon
          :closable="true"
          class="form-error"
          @close="errorMsg = ''"
        />

        <el-form
          ref="formRef"
          :model="form"
          :rules="rules"
          label-position="top"
          @submit.prevent="handleLogin"
        >
          <el-form-item label="用户名" prop="username">
            <el-input
              v-model="form.username"
              placeholder="请输入用户名"
              size="large"
              :prefix-icon="User"
              clearable
              @keyup.enter="handleLogin"
            />
          </el-form-item>

          <el-form-item label="密码" prop="password">
            <el-input
              v-model="form.password"
              type="password"
              placeholder="请输入密码"
              size="large"
              :prefix-icon="Lock"
              show-password
              @keyup.enter="handleLogin"
            />
          </el-form-item>

          <el-form-item>
            <el-button
              type="primary"
              size="large"
              class="submit-btn"
              :loading="loading"
              @click="handleLogin"
            >
              {{ loading ? '登录中…' : '登 录' }}
            </el-button>
          </el-form-item>
        </el-form>

        <el-alert
          title="默认管理员账户"
          description="用户名: admin · 密码: Admin123"
          type="info"
          :closable="false"
          class="form-hint"
        />
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
/**
 * 登录页：左侧 Lottie 品牌动效面板 + 右侧登录表单卡片。
 * 动画使用 lottie-web 渲染本地 JSON（src/assets/login-lottie.json）。
 */
import { ref, reactive, onMounted, onUnmounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { User, Lock, Monitor, Cpu, TrendCharts, CircleCheck } from '@element-plus/icons-vue'
import lottie, { type AnimationItem } from 'lottie-web'
import loginAnimationData from '@/assets/login-lottie.json'
import { useAuthStore } from '@/stores'

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()

const formRef = ref<FormInstance>()
const lottieRef = ref<HTMLDivElement | null>(null)
const loading = ref<boolean>(false)
const errorMsg = ref<string>('')

/** lottie 动画实例，onUnmounted 时销毁避免内存泄漏 */
let animation: AnimationItem | null = null

const form = reactive({
  username: 'admin',
  password: 'Admin123',
})

const rules: FormRules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
}

/** 执行登录 */
async function handleLogin(): Promise<void> {
  if (!formRef.value) return
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return

  errorMsg.value = ''
  loading.value = true
  try {
    const success = await authStore.login(form.username, form.password)
    if (success) {
      ElMessage.success('登录成功')
      const redirect = (route.query.redirect as string) || '/dashboard'
      router.push(redirect)
    } else {
      errorMsg.value = '登录失败，请检查用户名和密码'
    }
  } catch {
    errorMsg.value = '登录失败，请稍后重试'
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  if (!lottieRef.value) return
  animation = lottie.loadAnimation({
    container: lottieRef.value,
    renderer: 'svg',
    loop: true,
    autoplay: true,
    animationData: loginAnimationData,
  })
})

onUnmounted(() => {
  if (animation) {
    animation.destroy()
    animation = null
  }
})
</script>

<style scoped>
.login-page {
  display: flex;
  min-height: 100vh;
  background: #f5f7fb;
}

/* ==================== 左侧品牌面板 ==================== */
.brand-panel {
  position: relative;
  flex: 1 1 52%;
  overflow: hidden;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 48px;
  background: linear-gradient(135deg, #4b3ff5 0%, #6a5cff 45%, #9b6bff 100%);
  color: #fff;
}

.brand-bg {
  position: absolute;
  inset: 0;
  pointer-events: none;
}

.blob {
  position: absolute;
  border-radius: 50%;
  filter: blur(60px);
  opacity: 0.45;
}

.blob-a {
  width: 380px;
  height: 380px;
  top: -90px;
  left: -80px;
  background: #7de3ff;
  animation: float-a 14s ease-in-out infinite;
}

.blob-b {
  width: 320px;
  height: 320px;
  bottom: -100px;
  right: -60px;
  background: #ff8bd0;
  animation: float-b 18s ease-in-out infinite;
}

.blob-c {
  width: 260px;
  height: 260px;
  top: 45%;
  left: 60%;
  background: #ffd98b;
  opacity: 0.28;
  animation: float-a 22s ease-in-out infinite reverse;
}

@keyframes float-a {
  0%,
  100% {
    transform: translate3d(0, 0, 0) scale(1);
  }
  50% {
    transform: translate3d(40px, 60px, 0) scale(1.12);
  }
}

@keyframes float-b {
  0%,
  100% {
    transform: translate3d(0, 0, 0) scale(1);
  }
  50% {
    transform: translate3d(-50px, -40px, 0) scale(1.08);
  }
}

.brand-content {
  position: relative;
  z-index: 1;
  width: 100%;
  max-width: 460px;
  text-align: center;
}

.brand-logo {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  font-size: 17px;
  font-weight: 600;
  letter-spacing: 0.5px;
  opacity: 0.92;
}

.lottie-stage {
  width: 100%;
  max-width: 320px;
  height: 320px;
  margin: 8px auto 4px;
}

.brand-text {
  animation: rise-in 0.7s cubic-bezier(0.22, 1, 0.36, 1) both;
}

.brand-title {
  margin: 0;
  font-size: 34px;
  font-weight: 700;
  letter-spacing: 1px;
}

.brand-subtitle {
  margin: 12px 0 0;
  font-size: 15px;
  line-height: 1.7;
  opacity: 0.82;
}

.brand-features {
  display: flex;
  justify-content: center;
  gap: 12px;
  margin: 36px 0 0;
  padding: 0;
  list-style: none;
  animation: rise-in 0.9s cubic-bezier(0.22, 1, 0.36, 1) both;
}

.brand-features li {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 14px;
  font-size: 13px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.14);
  border: 1px solid rgba(255, 255, 255, 0.22);
  backdrop-filter: blur(6px);
  white-space: nowrap;
}

@keyframes rise-in {
  from {
    opacity: 0;
    transform: translateY(18px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

/* ==================== 右侧表单面板 ==================== */
.form-panel {
  flex: 1 1 48%;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 48px 32px;
}

.form-card {
  width: 100%;
  max-width: 400px;
  animation: rise-in 0.6s cubic-bezier(0.22, 1, 0.36, 1) both;
}

.form-head {
  margin-bottom: 28px;
}

.form-title {
  margin: 0;
  font-size: 26px;
  font-weight: 700;
  color: #1f2329;
}

.form-desc {
  margin: 8px 0 0;
  font-size: 14px;
  color: #8a9099;
}

.form-error {
  margin-bottom: 18px;
}

.submit-btn {
  width: 100%;
  margin-top: 6px;
  font-weight: 600;
  letter-spacing: 2px;
}

.form-hint {
  margin-top: 20px;
}

:deep(.el-form-item__label) {
  font-weight: 500;
  color: #4e5969;
  padding-bottom: 4px;
}

/* ==================== 响应式 ==================== */
@media (max-width: 960px) {
  .login-page {
    flex-direction: column;
  }

  .brand-panel {
    flex: none;
    padding: 40px 24px 32px;
  }

  .lottie-stage {
    max-width: 200px;
    height: 200px;
  }

  .brand-title {
    font-size: 26px;
  }

  .brand-features {
    flex-wrap: wrap;
    margin-top: 24px;
  }

  .form-panel {
    padding: 32px 24px 48px;
  }
}

@media (max-width: 480px) {
  .brand-features {
    display: none;
  }

  .lottie-stage {
    max-width: 160px;
    height: 160px;
  }
}
</style>
