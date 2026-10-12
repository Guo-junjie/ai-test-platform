<template>
  <div class="notifications-page">
    <el-card shadow="hover">
      <template #header>
        <div class="card-header">
          <div class="header-title">
            <span>消息通知</span>
            <el-badge :value="unreadCount" :hidden="unreadCount === 0" class="unread-badge" />
          </div>
          <div class="header-actions">
            <el-select
              v-model="filterRead"
              placeholder="全部"
              clearable
              size="default"
              style="width: 140px; margin-right: 8px;"
              @change="loadNotifications"
            >
              <el-option label="全部消息" :value="''" />
              <el-option label="仅未读" :value="'unread'" />
              <el-option label="仅已读" :value="'read'" />
            </el-select>
            <el-button :loading="loading" @click="loadNotifications">
              <el-icon><Refresh /></el-icon>
              刷新
            </el-button>
            <el-button
              type="primary"
              :disabled="unreadCount === 0"
              :loading="markingAll"
              @click="handleMarkAllRead"
            >
              全部已读
            </el-button>
          </div>
        </div>
      </template>

      <el-table :data="notifications" v-loading="loading" style="width: 100%">
        <el-table-column label="标题" min-width="200" show-overflow-tooltip>
          <template #default="{ row }">
            <span :class="{ unread: !isRead(row) }">{{ row.title }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="content" label="内容" min-width="280" show-overflow-tooltip />
        <el-table-column label="类型" width="120">
          <template #default="{ row }">
            <el-tag :type="typeTagType(row.type)" size="small">
              {{ typeLabels[row.type] || row.type || '通知' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="isRead(row) ? 'info' : 'warning'" size="small">
              {{ isRead(row) ? '已读' : '未读' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="创建时间" width="180">
          <template #default="{ row }">
            {{ formatTime(row.created_at) }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="240">
          <template #default="{ row }">
            <el-button v-if="row.related_url" size="small" type="primary" link @click="openNotification(row)">查看关联</el-button>
            <el-button
              size="small"
              type="primary"
              plain
              :disabled="isRead(row)"
              :loading="markingId === row.id"
              @click="handleMarkRead(row)"
            >
              标记已读
            </el-button>
            <el-button
              size="small"
              type="danger"
              plain
              :loading="removingId === row.id"
              @click="handleRemove(row)"
            >
              删除
            </el-button>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="暂无消息通知" />
        </template>
      </el-table>

      <el-pagination
        v-if="total > pageSize"
        background
        layout="prev, pager, next, total"
        :total="total"
        :page-size="pageSize"
        v-model:current-page="page"
        style="margin-top: 16px; justify-content: flex-end;"
        @current-change="loadNotifications"
      />
    </el-card>
    <el-card shadow="never" class="preference-card"><template #header><b>通知偏好</b></template><el-form label-position="top"><div class="pref-grid"><el-form-item label="接收通知"><el-switch v-model="preferences.enabled"/></el-form-item><el-form-item label="接收渠道"><el-select v-model="preferences.channels" multiple :disabled="!preferences.enabled"><el-option label="站内消息" value="in_app"/><el-option label="邮件" value="email"/><el-option label="Webhook" value="webhook"/><el-option label="钉钉" value="dingtalk"/></el-select></el-form-item><el-form-item label="免打扰"><el-switch v-model="preferences.quiet_enabled"/></el-form-item><el-form-item label="免打扰时段"><el-time-picker v-model="quietRange" is-range format="HH:mm" value-format="HH:mm" range-separator="至" start-placeholder="开始" end-placeholder="结束" :disabled="!preferences.quiet_enabled"/></el-form-item></div><el-button type="primary" :loading="savingPreferences" @click="savePreferences">保存通知偏好</el-button></el-form></el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { notificationApi } from '@/api'

const router = useRouter()

/** 通知类型 -> 中文标签 */
const typeLabels: Record<string, string> = {
  info: '信息',
  success: '成功',
  warning: '警告',
  error: '错误',
  test_run: '测试任务',
  quality_gate: '质量门禁',
  report: '报告',
  system: '系统',
  defect: '缺陷协作',
  case_review: '用例评审',
  case_generation: '用例生成',
}

const notifications = ref<any[]>([])
const loading = ref(false)
const markingAll = ref(false)
const markingId = ref<string>('')
const removingId = ref<string>('')
const unreadCount = ref(0)
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const filterRead = ref<string>('')
const savingPreferences = ref(false)
const preferences = ref({ enabled: true, channels: ['in_app'], quiet_enabled: false, quiet_start: '22:00', quiet_end: '08:00' })
const quietRange = ref<[string, string]>(['22:00', '08:00'])

/** 兼容后端可能使用 is_read 或 read 字段 */
function isRead(row: any): boolean {
  return row?.is_read ?? row?.read ?? false
}

async function openNotification(row: any): Promise<void> {
  if (!isRead(row)) await handleMarkRead(row)
  if (row.related_url) await router.push(row.related_url)
}

/** 通知类型对应的 tag 颜色 */
function typeTagType(type: string): 'success' | 'warning' | 'danger' | 'primary' | 'info' {
  const map: Record<string, 'success' | 'warning' | 'danger' | 'primary' | 'info'> = {
    success: 'success',
    warning: 'warning',
    error: 'danger',
    quality_gate: 'warning',
    test_run: 'primary',
    report: 'primary',
    info: 'info',
    system: 'info',
    defect: 'warning',
    case_review: 'primary',
    case_generation: 'success',
  }
  return map[type] || 'info'
}

/** 格式化 ISO 时间为本地可读格式 */
function formatTime(iso: string | null): string {
  if (!iso) return '-'
  try {
    return new Date(iso).toLocaleString('zh-CN', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    })
  } catch {
    return String(iso)
  }
}

/** 加载通知列表（含 total / unread_count） */
async function loadNotifications(): Promise<void> {
  loading.value = true
  try {
    const params: Record<string, any> = { page: page.value, page_size: pageSize.value }
    if (filterRead.value === 'unread') params.is_read = false
    if (filterRead.value === 'read') params.is_read = true

    const res: any = await notificationApi.list(params)
    const d = res?.data ?? res ?? {}
    const list = Array.isArray(d) ? d : d.items || d.list || []
    notifications.value = list
    total.value = Array.isArray(d) ? list.length : d.total ?? list.length
    unreadCount.value = Array.isArray(d)
      ? list.filter((n: any) => !isRead(n)).length
      : d.unread_count ?? list.filter((n: any) => !isRead(n)).length
  } catch {
    notifications.value = []
    total.value = 0
    unreadCount.value = 0
  } finally {
    loading.value = false
  }
}

/** 标记单条通知为已读 */
async function handleMarkRead(row: any): Promise<void> {
  markingId.value = row.id
  try {
    await notificationApi.markRead(row.id)
    row.is_read = true
    row.read = true
    unreadCount.value = Math.max(0, unreadCount.value - 1)
    ElMessage.success('已标记为已读')
  } catch (e: any) {
    ElMessage.error(e?.message || '操作失败')
  } finally {
    markingId.value = ''
  }
}

/** 标记全部通知为已读 */
async function handleMarkAllRead(): Promise<void> {
  markingAll.value = true
  try {
    await notificationApi.markAllRead()
    notifications.value.forEach((n) => {
      n.is_read = true
      n.read = true
    })
    unreadCount.value = 0
    ElMessage.success('已全部标记为已读')
  } catch (e: any) {
    ElMessage.error(e?.message || '操作失败')
  } finally {
    markingAll.value = false
  }
}

/** 删除通知（二次确认） */
async function handleRemove(row: any): Promise<void> {
  try {
    await ElMessageBox.confirm(`确认删除通知「${row.title}」吗？`, '删除确认', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
  } catch {
    return // 用户取消
  }

  removingId.value = row.id
  try {
    await notificationApi.remove(row.id)
    ElMessage.success('删除成功')
    await loadNotifications()
  } catch (e: any) {
    ElMessage.error(e?.message || '删除失败')
  } finally {
    removingId.value = ''
  }
}

async function loadPreferences(): Promise<void> { const res: any = await notificationApi.getPreferences(); preferences.value = { ...preferences.value, ...(res?.data || {}) }; quietRange.value = [preferences.value.quiet_start, preferences.value.quiet_end] }
async function savePreferences(): Promise<void> { savingPreferences.value = true; try { preferences.value.quiet_start = quietRange.value?.[0] || '22:00'; preferences.value.quiet_end = quietRange.value?.[1] || '08:00'; await notificationApi.updatePreferences(preferences.value); ElMessage.success('通知偏好已保存') } finally { savingPreferences.value = false } }

onMounted(() => Promise.all([loadNotifications(), loadPreferences()]))
</script>

<style scoped>
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.header-title {
  display: flex;
  align-items: center;
  gap: 12px;
}

.unread-badge {
  margin-top: -4px;
}

.header-actions {
  display: flex;
  align-items: center;
}

.unread {
  font-weight: 600;
  color: var(--el-text-color-primary);
}
.notifications-page{display:grid;gap:16px}.pref-grid{display:grid;grid-template-columns:160px 1.3fr 160px 1fr;gap:14px}.pref-grid .el-select{width:100%}@media(max-width:900px){.pref-grid{grid-template-columns:1fr 1fr}}@media(max-width:560px){.header-actions{flex-wrap:wrap;gap:8px}.pref-grid{grid-template-columns:1fr}}
</style>
