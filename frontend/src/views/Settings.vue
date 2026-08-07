<template>
  <div class="settings-page">
    <el-card shadow="hover">
      <el-tabs v-model="activeTab" @tab-change="handleTabChange">
        <!-- 基础设置 -->
        <el-tab-pane label="基础设置" name="basic">
          <el-form label-width="140px" style="max-width: 620px;" v-loading="loading">
            <el-form-item label="运行环境">
              <el-tag>{{ settings.app_env || 'development' }}</el-tag>
            </el-form-item>
            <el-form-item label="调试模式">
              <el-switch v-model="settings.app_debug" />
            </el-form-item>
            <el-form-item label="工作目录">
              <el-input v-model="settings.workspace_dir" disabled />
            </el-form-item>
            <el-form-item label="报告目录">
              <el-input v-model="settings.report_dir" disabled />
            </el-form-item>
            <el-form-item label="MinIO 端点">
              <el-input v-model="settings.minio_endpoint" disabled />
            </el-form-item>
            <el-form-item label="MinIO 桶">
              <el-input v-model="settings.minio_bucket" disabled />
            </el-form-item>
            <el-form-item label="PostgreSQL">
              <el-input :model-value="`${settings.postgres_host}:${settings.postgres_port}`" disabled />
            </el-form-item>
            <el-form-item label="Redis">
              <el-input :model-value="`${settings.redis_host}:${settings.redis_port}`" disabled />
            </el-form-item>
            <el-form-item label="平台名称">
              <el-input v-model="custom.platform_name" placeholder="AI 自动化测试平台" />
            </el-form-item>
            <el-form-item label="默认超时(秒)">
              <el-input-number :min="5" v-model="custom.default_timeout" />
            </el-form-item>
            <el-form-item>
              <el-button type="primary" :loading="saving" @click="saveBasic">保存基础配置</el-button>
            </el-form-item>
          </el-form>
        </el-tab-pane>

        <!-- 通知配置 -->
        <el-tab-pane label="通知配置" name="notification">
          <el-form label-width="140px" style="max-width: 620px;" v-loading="notifLoading">
            <el-divider content-position="left">Webhook</el-divider>
            <el-form-item label="Webhook URL">
              <el-input v-model="notification.webhook_url" placeholder="https://example.com/hook" />
            </el-form-item>
            <el-divider content-position="left">钉钉</el-divider>
            <el-form-item label="钉钉 Webhook">
              <el-input v-model="notification.dingtalk_webhook" placeholder="https://oapi.dingtalk.com/robot/send?access_token=..." />
            </el-form-item>
            <el-divider content-position="left">邮件 SMTP</el-divider>
            <el-form-item label="SMTP 主机">
              <el-input v-model="notification.smtp_host" placeholder="smtp.example.com" />
            </el-form-item>
            <el-form-item label="SMTP 端口">
              <el-input-number :min="1" :max="65535" v-model="notification.smtp_port" />
            </el-form-item>
            <el-form-item label="SMTP 用户">
              <el-input v-model="notification.smtp_user" />
            </el-form-item>
            <el-form-item label="SMTP 密码">
              <el-input v-model="notification.smtp_password" type="password" show-password />
            </el-form-item>
            <el-form-item label="发件人">
              <el-input v-model="notification.email_from" />
            </el-form-item>
            <el-form-item label="收件人">
              <el-select
                v-model="notification.email_to"
                multiple
                filterable
                allow-create
                default-first-option
                placeholder="输入邮箱后回车"
                style="width: 100%;"
              />
            </el-form-item>
            <el-form-item>
              <el-button type="primary" :loading="savingNotif" @click="saveNotification">保存通知配置</el-button>
            </el-form-item>
          </el-form>
        </el-tab-pane>

        <!-- 个人设置 -->
        <el-tab-pane label="个人设置" name="profile">
          <ProfileSettings />
        </el-tab-pane>
      </el-tabs>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { systemApi } from '@/api'
import ProfileSettings from '@/components/ProfileSettings.vue'

const activeTab = ref('basic')
const loading = ref(false)
const saving = ref(false)
const notifLoading = ref(false)
const savingNotif = ref(false)

const settings = reactive<any>({
  app_env: '',
  app_debug: false,
  workspace_dir: '',
  report_dir: '',
  minio_endpoint: '',
  minio_bucket: '',
  redis_host: '',
  redis_port: '',
  postgres_host: '',
  postgres_port: '',
  postgres_db: '',
  custom: {},
})

const custom = reactive({
  platform_name: '',
  default_timeout: 30,
})

const notification = reactive({
  webhook_url: '',
  dingtalk_webhook: '',
  smtp_host: '',
  smtp_port: 587,
  smtp_user: '',
  smtp_password: '',
  email_from: '',
  email_to: [] as string[],
})

async function loadSettings() {
  loading.value = true
  try {
    const res: any = await systemApi.getSettings()
    const d = res.data || {}
    Object.assign(settings, d)
    Object.assign(custom, d.custom || {})
  } catch {
    /* 忽略 */
  } finally {
    loading.value = false
  }
}

async function saveBasic() {
  saving.value = true
  try {
    await systemApi.updateSettings({ ...custom })
    ElMessage.success('基础配置保存成功')
  } catch (e: any) {
    ElMessage.error(e?.message || '保存失败')
  } finally {
    saving.value = false
  }
}

async function loadNotification() {
  notifLoading.value = true
  try {
    const res: any = await systemApi.getNotificationConfig()
    Object.assign(notification, res.data || {})
  } catch {
    /* 忽略 */
  } finally {
    notifLoading.value = false
  }
}

async function saveNotification() {
  savingNotif.value = true
  try {
    await systemApi.updateNotificationConfig({ ...notification })
    ElMessage.success('通知配置保存成功')
  } catch (e: any) {
    ElMessage.error(e?.message || '保存失败')
  } finally {
    savingNotif.value = false
  }
}

function handleTabChange(name: string | number) {
  if (name === 'notification') loadNotification()
}

onMounted(loadSettings)
</script>
