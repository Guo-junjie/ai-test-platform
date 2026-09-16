<template>
  <el-badge :value="unreadCount" :hidden="unreadCount === 0" class="notification-badge">
    <el-dropdown trigger="click" @command="handleCommand">
      <el-icon :size="20" class="bell-icon"><Bell /></el-icon>
      <template #dropdown>
        <el-dropdown-menu class="notification-menu">
          <el-dropdown-item v-if="notifications.length === 0" disabled>
            暂无通知
          </el-dropdown-item>
          <el-dropdown-item
            v-for="n in notifications"
            :key="n.id"
            :command="n.id"
            :divided="n !== notifications[0]"
          >
            <div class="notification-item">
              <div class="notif-title" :class="{ unread: !n.read }">{{ n.title }}</div>
              <div class="notif-time">{{ formatTime(n.created_at) }}</div>
            </div>
          </el-dropdown-item>
          <el-dropdown-item divided command="clear" v-if="unreadCount > 0">
            <span class="clear-text">全部已读</span>
          </el-dropdown-item>
          <el-dropdown-item :divided="unreadCount === 0" command="viewAll">
            <span class="clear-text">查看全部通知</span>
          </el-dropdown-item>
        </el-dropdown-menu>
      </template>
    </el-dropdown>
  </el-badge>
</template>

<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { notificationApi } from '@/api'
import { safeGetItem } from '@/utils/safeStorage'

interface Notification {
  id: string
  title: string
  content?: string
  read: boolean
  created_at: string
}

const router = useRouter()
const notifications = ref<Notification[]>([])
const unreadCount = ref(0)
let timer: ReturnType<typeof setInterval> | null = null

/** 兼容后端可能使用 is_read 或 read 字段 */
function normalize(raw: any): Notification {
  return {
    id: String(raw?.id ?? ''),
    title: raw?.title || '（无标题）',
    content: raw?.content || '',
    read: raw?.is_read ?? raw?.read ?? false,
    created_at: raw?.created_at || new Date().toISOString(),
  }
}

/** 轮询拉取最新通知（仅展示最近 10 条） */
async function loadNotifications() {
  // 未登录（无 token）时不发起请求，避免登录页 / 未认证状态下产生 401 噪音
  if (!safeGetItem('token')) {
    notifications.value = []
    unreadCount.value = 0
    return
  }
  try {
    const res: any = await notificationApi.list({ page: 1, page_size: 10 })
    const d = res?.data ?? res ?? {}
    const list = Array.isArray(d) ? d : d.items || d.list || []
    notifications.value = list
      .map(normalize)
      .sort((a: Notification, b: Notification) =>
        new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
      )
    unreadCount.value = Array.isArray(d)
      ? notifications.value.filter((n) => !n.read).length
      : d.unread_count ?? notifications.value.filter((n) => !n.read).length
  } catch {
    // 静默失败：通知不可用时不打断主流程
    notifications.value = []
    unreadCount.value = 0
  }
}

function formatTime(iso: string): string {
  try {
    const d = new Date(iso)
    return d.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
  } catch {
    return ''
  }
}

async function handleCommand(cmd: string | number) {
  if (cmd === 'viewAll') {
    router.push('/notifications')
    return
  }

  if (cmd === 'clear') {
    try {
      await notificationApi.markAllRead()
      notifications.value.forEach((n) => (n.read = true))
      unreadCount.value = 0
      ElMessage.success('已全部标记为已读')
    } catch {
      /* 错误提示已由 axios 响应拦截器统一处理 */
    }
    return
  }

  const target = notifications.value.find((n) => n.id === String(cmd))
  if (target && !target.read) {
    try {
      await notificationApi.markRead(target.id)
      target.read = true
      unreadCount.value = notifications.value.filter((n) => !n.read).length
    } catch {
      /* 错误提示已由 axios 响应拦截器统一处理 */
    }
  }
}

onMounted(() => {
  loadNotifications()
  timer = setInterval(loadNotifications, 60000)
})

onBeforeUnmount(() => {
  if (timer) clearInterval(timer)
})
</script>

<style scoped>
/* 间距交由父级（顶栏 header-right 的 gap）统一控制，这里不再叠加右边距 */
.notification-badge {
  margin-right: 0;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
}

.bell-icon {
  color: var(--app-text-secondary);
  vertical-align: middle;
  transition: color 0.16s ease;
}

.notification-badge:hover .bell-icon {
  color: var(--app-accent);
}

.notification-menu {
  min-width: 260px;
  /* 通知较多时限制下拉高度并内部滚动，避免超出视口 */
  max-height: min(60vh, 520px);
  overflow-y: auto;
}

.notification-item {
  display: flex;
  flex-direction: column;
  padding: 4px 0;
}

.notif-title {
  font-size: var(--app-fs-sm);
  color: var(--app-text-regular);
}

.notif-title.unread {
  font-weight: 600;
  color: var(--app-text-primary);
}

.notif-time {
  font-size: var(--app-fs-xs);
  color: var(--app-text-placeholder);
  margin-top: 2px;
}

.clear-text {
  color: var(--app-accent);
  font-size: var(--app-fs-sm);
}
</style>
