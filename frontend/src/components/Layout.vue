<template>
  <el-container class="layout-container">
    <!-- 侧边栏 -->
    <el-aside :width="isCollapse ? '64px' : '220px'" class="sidebar">
      <div class="logo">
        <el-icon size="24" color="#409eff"><Monitor /></el-icon>
        <span v-show="!isCollapse" class="logo-text">AI 测试平台</span>
      </div>
      <el-menu
        :default-active="activeMenu"
        :collapse="isCollapse"
        router
        background-color="#001529"
        text-color="#ffffffa6"
        active-text-color="#ffffff"
      >
        <el-menu-item index="/dashboard">
          <el-icon><DataLine /></el-icon>
          <span>仪表盘</span>
        </el-menu-item>
        <el-menu-item index="/test-run">
          <el-icon><VideoPlay /></el-icon>
          <span>测试运行</span>
        </el-menu-item>
        <el-menu-item index="/quality-trend">
          <el-icon><TrendCharts /></el-icon>
          <span>质量趋势</span>
        </el-menu-item>
        <el-menu-item index="/sources">
          <el-icon><Connection /></el-icon>
          <span>数据源管理</span>
        </el-menu-item>

        <el-menu-item index="/analysis">
          <el-icon><Search /></el-icon>
          <span>代码解析</span>
        </el-menu-item>

        <el-menu-item index="/notifications">
          <el-icon><Bell /></el-icon>
          <span>消息通知</span>
        </el-menu-item>

        <el-menu-item v-if="authStore.isAdmin" index="/user-management">
          <el-icon><UserFilled /></el-icon>
          <span>用户管理</span>
        </el-menu-item>

        <el-menu-item v-if="canAudit" index="/approvals">
          <el-icon><CircleCheck /></el-icon>
          <span>审核中心</span>
        </el-menu-item>

        <el-sub-menu index="settings">
          <template #title>
            <el-icon><Setting /></el-icon>
            <span>系统配置</span>
          </template>
          <el-menu-item v-if="authStore.isAdmin" index="/settings">基础配置</el-menu-item>
          <el-menu-item v-if="authStore.isAdmin" index="/settings/models">AI 模型配置</el-menu-item>
          <el-menu-item index="/settings/quality-gate">质量门禁</el-menu-item>
          <el-menu-item index="/settings/audit">审计日志</el-menu-item>
          <el-menu-item index="/profile">个人设置</el-menu-item>
        </el-sub-menu>
      </el-menu>
    </el-aside>

    <!-- 主内容区 -->
    <el-container>
      <el-header class="header">
        <div class="header-left">
          <el-icon class="collapse-btn" @click="isCollapse = !isCollapse">
            <Fold v-if="!isCollapse" />
            <Expand v-else />
          </el-icon>
          <el-breadcrumb separator="/">
            <el-breadcrumb-item :to="{ path: '/' }">首页</el-breadcrumb-item>
            <el-breadcrumb-item>{{ currentTitle }}</el-breadcrumb-item>
          </el-breadcrumb>
        </div>
        <div class="header-right">
          <NotificationBell />
          <el-dropdown @command="handleUserCommand">
            <span class="user-info">
              <el-avatar :size="32" icon="UserFilled" />
              <span class="username">{{ authStore.username }}</span>
              <el-tag size="small" :type="roleTagType" effect="plain">{{ roleLabel }}</el-tag>
            </span>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="profile">个人设置</el-dropdown-item>
                <el-dropdown-item command="logout" divided>退出登录</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </el-header>

      <el-main class="main-content">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import NotificationBell from '@/components/NotificationBell.vue'
import { useAuthStore } from '@/stores'
import { roleLabel as toRoleLabel, roleTagType as toRoleTagType } from '@/utils/roles'

const route = useRoute()
const router = useRouter()
const isCollapse = ref(false)
const authStore = useAuthStore()

const activeMenu = computed(() => route.path)
const currentTitle = computed(() => (route.meta?.title as string) || '')

/** 审核中心可见性：审核员或超级管理员 */
const canAudit = computed<boolean>(() => authStore.isAuditor || authStore.isSuperAdmin)

/** 当前用户角色中文名（统一取自角色字典） */
const roleLabel = computed<string>(() => toRoleLabel(authStore.role))

/** 当前用户角色 tag 颜色（统一取自角色字典） */
const roleTagType = computed(() => toRoleTagType(authStore.role))

function handleUserCommand(cmd: string) {
  if (cmd === 'logout') {
    authStore.logout()
    ElMessage.success('已退出登录')
    router.push('/login')
  } else if (cmd === 'profile') {
    router.push('/profile')
  }
}
</script>

<style scoped>
.layout-container {
  height: 100vh;
}

.sidebar {
  background-color: #001529;
  transition: width 0.3s;
  overflow: hidden;
}

.logo {
  height: 60px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  border-bottom: 1px solid #ffffff1a;
}

.logo-text {
  color: #fff;
  font-size: 16px;
  font-weight: 600;
  white-space: nowrap;
}

.header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: #fff;
  border-bottom: 1px solid #e8e8e8;
  padding: 0 20px;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 16px;
}

.collapse-btn {
  font-size: 20px;
  cursor: pointer;
  color: #666;
}

.header-right {
  display: flex;
  align-items: center;
}

.user-info {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
}

.username {
  font-size: 14px;
  color: #333;
}

.main-content {
  background-color: #f0f2f5;
  padding: 20px;
  overflow-y: auto;
}

:deep(.el-menu) {
  border-right: none;
}
</style>
