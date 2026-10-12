<template>
  <el-container class="layout-container">
    <el-aside id="platform-navigation" class="sidebar" :class="{ 'mobile-sidebar': isMobile, 'mobile-open': mobileMenuOpen }" :aria-hidden="isMobile && !mobileMenuOpen ? true : undefined" :inert="isMobile && !mobileMenuOpen">
      <router-link class="logo" to="/dashboard" aria-label="返回工作台">
        <span class="logo-mark"><el-icon><Promotion /></el-icon></span>
        <span class="logo-text">AI 测试平台</span>
      </router-link>

      <el-menu :default-active="activeMenu" router @select="onMenuSelect">
        <div v-for="(group, index) in visibleGroups" :key="group.title || index" class="nav-group">
          <div v-if="group.title" class="menu-group-title">
            <span>{{ group.title }}</span>
            <span v-if="group.lock" class="group-lock">{{ group.lock }}</span>
          </div>
          <el-menu-item v-for="item in group.items" :key="item.path" :index="item.path">
            <el-icon class="nav-icon"><component :is="NAV_ICONS[item.icon]" /></el-icon>
            <template #title><span class="nav-label">{{ item.label }}</span></template>
          </el-menu-item>
        </div>
      </el-menu>
    </el-aside>

    <div v-if="isMobile && mobileMenuOpen" class="mobile-mask" aria-hidden="true" @click="mobileMenuOpen = false"></div>

    <el-container class="content-shell">
      <el-header class="header">
        <div class="header-left">
          <button v-if="isMobile" type="button" class="icon-button" aria-label="打开导航菜单" aria-controls="platform-navigation" :aria-expanded="mobileMenuOpen" @click="toggleNavigation">
            <el-icon><Expand /></el-icon>
          </button>
          <el-breadcrumb separator="/" class="breadcrumb">
            <el-breadcrumb-item :to="{ path: '/dashboard' }">首页</el-breadcrumb-item>
            <el-breadcrumb-item v-if="currentGroup">{{ currentGroup }}</el-breadcrumb-item>
            <el-breadcrumb-item>{{ currentTitle }}</el-breadcrumb-item>
          </el-breadcrumb>
        </div>

        <div class="header-right">
          <button type="button" class="global-search" aria-label="全局搜索" @click="searchOpen = true">
            <el-icon><Search /></el-icon>
            <span>搜索用例 / 计划 / 缺陷…</span>
            <kbd>Ctrl K</kbd>
          </button>
          <NotificationBell />
          <el-dropdown trigger="click" placement="bottom-end" popper-class="account-dropdown" @command="handleUserCommand">
            <span class="user-info" aria-label="账号菜单">
              <el-avatar class="user-avatar" :size="28">{{ avatarText }}</el-avatar>
              <span class="account-name">{{ authStore.username }}</span>
              <span class="account-role">{{ authStore.roleName }}</span>
              <el-icon class="account-caret"><ArrowDown /></el-icon>
            </span>
            <template #dropdown>
              <div class="account-panel">
                <div class="account-summary">
                  <strong>{{ authStore.username }}</strong>
                  <span>{{ authStore.roleName }}<template v-if="authStore.user?.email"> · {{ authStore.user.email }}</template></span>
                </div>
                <el-dropdown-menu>
                  <el-dropdown-item command="profile"><el-icon><User /></el-icon>个人设置</el-dropdown-item>
                  <el-dropdown-item command="notifications"><el-icon><Bell /></el-icon>消息通知</el-dropdown-item>
                </el-dropdown-menu>
                <div class="account-appearance"><UiVariantSwitch /></div>
                <el-dropdown-menu class="account-logout">
                  <el-dropdown-item command="logout"><el-icon><SwitchButton /></el-icon>退出登录</el-dropdown-item>
                </el-dropdown-menu>
              </div>
            </template>
          </el-dropdown>
        </div>
      </el-header>

      <el-main class="main-content"><div class="view-frame"><router-view /></div></el-main>
    </el-container>

    <el-dialog v-model="searchOpen" title="全局搜索" width="560px" class="search-dialog" @opened="focusSearch">
      <el-input ref="searchInput" v-model="searchText" size="large" clearable placeholder="搜索功能、项目、用例或缺陷" :prefix-icon="Search" />
      <div class="search-results">
        <button v-for="item in searchResults" :key="item.path" type="button" @click="goSearch(item.path)">
          <span>{{ item.label }}</span><small>{{ item.path }}</small>
        </button>
        <el-empty v-if="searchResults.length === 0" description="没有匹配的功能" :image-size="56" />
      </div>
    </el-dialog>
  </el-container>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  Aim, ArrowDown, Bell, Box, ChatDotRound, Clock, Coin, Collection,
  CollectionTag, Connection, Cpu, DataAnalysis, DocumentChecked, Expand, Files,
  FolderOpened, HomeFilled, List, Lock, MagicStick, Notebook, Promotion, Search,
  Setting, Share, SwitchButton, Tickets, TrendCharts, User, VideoPlay, Warning,
} from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import NotificationBell from '@/components/NotificationBell.vue'
import UiVariantSwitch from '@/components/UiVariantSwitch.vue'
import { NAV_GROUPS, NAV_ITEMS, type NavIcon } from '@/constants/nav'
import { useAuthStore } from '@/stores'

const NAV_ICONS: Record<NavIcon, unknown> = {
  home: HomeFilled, folder: FolderOpened, spark: MagicStick, layers: CollectionTag,
  code: DocumentChecked, play: VideoPlay, flow: Share, clock: Clock, list: List,
  report: Tickets, analytics: DataAnalysis, target: Aim, trend: TrendCharts,
  bug: Warning, gate: Lock, book: Collection, chat: ChatDotRound, doc: Files,
  cube: Box, git: Connection, db: Coin, cpu: Cpu, settings: Setting, users: User,
  scroll: Notebook,
}

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const isMobile = ref(false)
const mobileMenuOpen = ref(false)
const searchOpen = ref(false)
const searchText = ref('')
const searchInput = ref<any>()

const visibleGroups = computed(() => NAV_GROUPS
  .map(group => ({
    ...group,
    items: group.items.filter(item =>
      (!item.admin || authStore.isAdmin) &&
      (!item.audit || authStore.isAdmin || authStore.isAuditor)
    ),
  }))
  .filter(group => group.items.length))
const activeMenu = computed(() => route.path.startsWith('/runs') ? '/runs' : route.path)
const currentTitle = computed(() => String(route.meta?.title || NAV_ITEMS.find(item => route.path.startsWith(item.path))?.label || '工作台'))
const currentGroup = computed(() => visibleGroups.value.find(group => group.items.some(item => route.path.startsWith(item.path)))?.title || '')
const avatarText = computed(() => (authStore.username || 'U').trim().slice(0, 1).toUpperCase())
const searchResults = computed(() => {
  const q = searchText.value.trim().toLowerCase()
  return visibleGroups.value.flatMap(group => group.items)
    .filter(item => !q || item.label.toLowerCase().includes(q) || item.path.includes(q))
    .slice(0, 12)
})

function updateViewport() {
  isMobile.value = window.innerWidth <= 860
  if (!isMobile.value) mobileMenuOpen.value = false
}
function toggleNavigation() { mobileMenuOpen.value = !mobileMenuOpen.value }
function onMenuSelect() { if (isMobile.value) mobileMenuOpen.value = false }
function focusSearch() { nextTick(() => searchInput.value?.focus()) }
function goSearch(path: string) { searchOpen.value = false; searchText.value = ''; router.push(path) }
function onShortcut(event: KeyboardEvent) {
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
    event.preventDefault()
    searchOpen.value = true
  }
}
function handleUserCommand(command: string) {
  if (command === 'logout') {
    authStore.logout()
    ElMessage.success('已退出登录')
    router.push('/login')
    return
  }
  router.push(command === 'profile' ? '/profile' : '/notifications')
}

onMounted(() => {
  updateViewport()
  window.addEventListener('resize', updateViewport)
  window.addEventListener('keydown', onShortcut)
})
onBeforeUnmount(() => {
  window.removeEventListener('resize', updateViewport)
  window.removeEventListener('keydown', onShortcut)
})
</script>

<style scoped>
.layout-container { height: 100vh; }
.content-shell { min-width: 0; }
.sidebar { width: var(--app-sidebar-width); background: var(--app-sidebar-bg); border-right: 1px solid var(--app-sidebar-border); display: flex; flex-direction: column; overflow: hidden; transition: transform .2s ease; }
.logo { height: var(--app-header-height); flex: none; display: flex; align-items: center; gap: 9px; padding: 0 16px; border-bottom: 1px solid var(--app-sidebar-divider); color: var(--app-sidebar-brand-text); text-decoration: none; }
.logo-mark { width: 26px; height: 26px; border-radius: 7px; display: grid; place-items: center; flex: none; color: var(--app-accent); background: var(--app-accent-weak); }
.logo-mark .el-icon { font-size: 15px; }
.logo-text { font-size: 15px; font-weight: 600; white-space: nowrap; }
:deep(.el-menu) { flex: 1; overflow-y: auto; padding: 8px 0 22px; border: 0; background: transparent; }
.nav-group { display: block; padding: 0 8px; margin-top: 12px; }
.nav-group:first-child { margin-top: 2px; }
.menu-group-title { display: flex; align-items: center; gap: 6px; padding: 6px 8px 5px; color: var(--app-sidebar-group-text); font-size: 11px; font-weight: 600; letter-spacing: .5px; }
.group-lock { margin-left: auto; font-size: 10px; font-weight: 500; letter-spacing: 0; opacity: .78; }
:deep(.el-menu-item) { height: 36px; line-height: 36px; gap: 9px; margin: 1px 0; padding: 0 10px !important; border-radius: var(--app-radius-md); color: var(--app-sidebar-text); font-size: 13.5px; background: transparent; }
:deep(.el-menu-item:hover) { color: var(--app-text-primary); background: var(--app-sidebar-item-hover-bg); }
:deep(.el-menu-item.is-active) { color: var(--app-sidebar-item-active-text); background: var(--app-sidebar-item-active-bg); font-weight: 500; }
.nav-icon { width: 16px; height: 16px; margin: 0; font-size: 16px; opacity: .9; }
.nav-label { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.header { height: var(--app-header-height); flex: none; display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 0 20px; background: var(--app-header-bg); border-bottom: 1px solid var(--app-header-border); }
.header-left, .header-right, .user-info { display: flex; align-items: center; }
.header-left { min-width: 0; }
.header-right { gap: 16px; flex: none; }
.breadcrumb { min-width: 0; font-size: 12.5px; }
:deep(.breadcrumb .el-breadcrumb__inner) { color: var(--app-text-placeholder); font-weight: 400; white-space: nowrap; }
:deep(.breadcrumb .el-breadcrumb__item:last-child .el-breadcrumb__inner) { color: var(--app-text-regular); font-weight: 500; }
.global-search { width: 270px; height: 34px; display: flex; align-items: center; gap: 8px; padding: 0 11px; border: 1px solid var(--app-border-light); border-radius: var(--app-radius-md); color: var(--app-text-placeholder); background: var(--app-fill-lighter); font: inherit; font-size: 13px; cursor: pointer; }
.global-search:hover { background: #fff; border-color: var(--app-border-base); }
.global-search > span { flex: 1; min-width: 0; overflow: hidden; text-align: left; text-overflow: ellipsis; white-space: nowrap; }
.global-search kbd { padding: 1px 5px; border: 1px solid var(--app-border-light); border-radius: 4px; color: var(--app-text-placeholder); background: #fff; font: 10.5px var(--app-font-mono); }
.user-info { gap: 8px; padding: 3px 6px 3px 3px; border-radius: var(--app-radius-md); cursor: pointer; outline: none; }
.user-info:hover { background: var(--app-fill-lighter); }
.user-avatar { flex: none; color: #fff; background: linear-gradient(135deg, #4f7ef0, #2563eb); font-size: 11.5px; font-weight: 600; }
.account-name { color: var(--app-text-regular); font-size: 13px; white-space: nowrap; }
.account-role { padding: 0 6px; border-radius: var(--app-radius-sm); color: #525a6a; background: #f0f1f4; font-size: 11px; font-weight: 500; line-height: 18px; white-space: nowrap; }
.account-caret { color: var(--app-text-placeholder); font-size: 13px; }
.account-panel { width: 224px; padding: 6px; }
.account-summary { display: flex; flex-direction: column; padding: 8px 10px 10px; margin-bottom: 4px; border-bottom: 1px solid var(--app-border-lighter); }
.account-summary strong { color: var(--app-text-primary); font-size: 13.5px; }
.account-summary span { overflow: hidden; margin-top: 2px; color: var(--app-text-placeholder); font-size: 11.5px; text-overflow: ellipsis; white-space: nowrap; }
.account-panel :deep(.el-dropdown-menu) { padding: 0; box-shadow: none; }
.account-panel :deep(.el-dropdown-menu__item) { gap: 9px; padding: 8px 10px; border-radius: var(--app-radius-sm); color: var(--app-text-regular); font-size: 13px; }
.account-appearance { padding: 3px 0; border-top: 1px solid var(--app-border-lighter); border-bottom: 1px solid var(--app-border-lighter); }
.account-appearance :deep(.ui-variant-trigger) { width: 100%; height: 34px; justify-content: flex-start; padding: 0 10px; border-color: transparent; font-size: 13px; }
.account-appearance :deep(.ui-variant-trigger__icon) { color: var(--app-text-placeholder); }
.account-logout { margin-top: 3px; }
.main-content { min-width: 0; padding: var(--app-page-padding); overflow: auto; background: var(--app-bg-page); }
.view-frame { width: 100%; min-height: 100%; max-width: 1440px; margin: 0 auto; }
.icon-button { width: 34px; height: 34px; display: grid; place-items: center; border: 0; border-radius: var(--app-radius-md); color: var(--app-text-secondary); background: transparent; cursor: pointer; }
.icon-button:hover { color: var(--app-text-primary); background: var(--app-fill-lighter); }
.search-results { display: grid; gap: 6px; max-height: 360px; margin-top: 14px; overflow: auto; }
.search-results button { display: flex; justify-content: space-between; padding: 11px 12px; border: 1px solid transparent; border-radius: 7px; color: var(--app-text-primary); background: var(--app-bg-page); cursor: pointer; }
.search-results button:hover { border-color: var(--app-accent); background: var(--app-accent-weak); }
.search-results small { color: var(--app-text-placeholder); }
.mobile-mask { display: none; }

@media (max-width: 1180px) {
  .global-search { width: 168px; min-width: 112px; }
  .global-search kbd, .account-role { display: none; }
}
@media (max-width: 860px) {
  .mobile-sidebar { position: fixed; inset: 0 auto 0 0; z-index: 900; width: 224px; transform: translateX(-100%); box-shadow: var(--app-shadow-lg); }
  .mobile-sidebar.mobile-open { transform: translateX(0); }
  .mobile-mask { position: fixed; inset: 0; z-index: 899; display: block; background: rgba(15, 23, 42, .42); }
  .header { padding: 0 12px; }
  .breadcrumb { display: none; }
  .global-search { width: 36px; min-width: 36px; padding: 0; justify-content: center; }
  .global-search span, .global-search kbd, .account-name, .account-role { display: none; }
  .header-right { gap: 8px; }
  .main-content { padding: 12px; overflow-x: hidden; }
}
</style>
