<template>
  <el-container class="layout-container">
    <el-aside :width="sidebarWidth" class="sidebar" :class="{ 'mobile-sidebar': isMobile, 'mobile-open': mobileMenuOpen }">
      <div class="logo"><span class="logo-mark">AI</span><div v-show="!isCollapse || isMobile" class="logo-copy"><strong>测试平台</strong><small>AI Quality Platform</small></div></div>
      <el-menu :default-active="activeMenu" :collapse="!isMobile && isCollapse" router @select="onMenuSelect">
        <template v-for="(group, index) in visibleGroups" :key="group.title || index">
          <div v-if="group.title && (!isCollapse || isMobile)" class="menu-group-title">{{ group.title }}</div>
          <el-menu-item v-for="item in group.items" :key="item.path" :index="item.path"><span class="nav-dot" aria-hidden="true"></span><template #title>{{ item.label }}</template></el-menu-item>
        </template>
      </el-menu>
      <button class="sidebar-collapse" :aria-label="isCollapse ? '展开导航' : '折叠导航'" @click="toggleNavigation"><el-icon><Expand v-if="isCollapse" /><Fold v-else /></el-icon><span v-if="!isCollapse">收起导航</span></button>
    </el-aside>
    <div v-if="isMobile && mobileMenuOpen" class="mobile-mask" aria-hidden="true" @click="mobileMenuOpen = false"></div>
    <el-container class="content-shell">
      <el-header class="header">
        <div class="header-left">
          <el-button v-if="isMobile" text aria-label="打开导航菜单" @click="toggleNavigation"><el-icon><Expand /></el-icon></el-button>
          <el-breadcrumb separator="/" class="breadcrumb"><el-breadcrumb-item :to="{ path: '/dashboard' }">首页</el-breadcrumb-item><el-breadcrumb-item v-if="currentGroup">{{ currentGroup }}</el-breadcrumb-item><el-breadcrumb-item>{{ currentTitle }}</el-breadcrumb-item></el-breadcrumb>
        </div>
        <div class="header-right">
          <button class="global-search" aria-label="全局搜索" @click="searchOpen = true"><el-icon><Search /></el-icon><span>搜索功能、项目、用例</span><kbd>Ctrl K</kbd></button>
          <UiVariantSwitch /><NotificationBell />
          <el-dropdown @command="handleUserCommand"><span class="user-info"><el-avatar :size="30">{{ (authStore.username || 'U').slice(0, 1).toUpperCase() }}</el-avatar><span class="username">{{ authStore.username }}</span><el-icon><ArrowDown /></el-icon></span><template #dropdown><el-dropdown-menu><el-dropdown-item command="profile">个人设置</el-dropdown-item><el-dropdown-item command="notifications">消息通知</el-dropdown-item><el-dropdown-item command="logout" divided>退出登录</el-dropdown-item></el-dropdown-menu></template></el-dropdown>
        </div>
      </el-header>
      <el-main class="main-content"><router-view /></el-main>
    </el-container>
    <el-dialog v-model="searchOpen" title="全局搜索" width="560px" class="search-dialog" @opened="focusSearch">
      <el-input ref="searchInput" v-model="searchText" size="large" clearable placeholder="输入功能名称" :prefix-icon="Search" />
      <div class="search-results"><button v-for="item in searchResults" :key="item.path" @click="goSearch(item.path)"><span>{{ item.label }}</span><small>{{ item.path }}</small></button><el-empty v-if="searchResults.length === 0" description="没有匹配的功能" :image-size="56" /></div>
    </el-dialog>
  </el-container>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowDown, Expand, Fold, Search } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import NotificationBell from '@/components/NotificationBell.vue'
import UiVariantSwitch from '@/components/UiVariantSwitch.vue'
import { NAV_GROUPS, NAV_ITEMS } from '@/constants/nav'
import { useAuthStore } from '@/stores'

const route = useRoute(); const router = useRouter(); const authStore = useAuthStore()
const isCollapse = ref(false); const isMobile = ref(false); const mobileMenuOpen = ref(false)
const searchOpen = ref(false); const searchText = ref(''); const searchInput = ref<any>()
const sidebarWidth = computed(() => isMobile.value ? '224px' : isCollapse.value ? '64px' : '224px')
const visibleGroups = computed(() => NAV_GROUPS.map(group => ({ ...group, items: group.items.filter(item => (!item.admin || authStore.isAdmin) && (!item.audit || authStore.isAdmin || authStore.isAuditor)) })).filter(group => group.items.length))
const activeMenu = computed(() => route.path.startsWith('/runs') ? '/runs' : route.path)
const currentTitle = computed(() => String(route.meta?.title || NAV_ITEMS.find(item => route.path.startsWith(item.path))?.label || '工作台'))
const currentGroup = computed(() => visibleGroups.value.find(group => group.items.some(item => route.path.startsWith(item.path)))?.title || '')
const searchResults = computed(() => { const q = searchText.value.trim().toLowerCase(); return visibleGroups.value.flatMap(g => g.items).filter(i => !q || i.label.toLowerCase().includes(q) || i.path.includes(q)).slice(0, 12) })
function updateViewport() { isMobile.value = window.innerWidth <= 768; if (!isMobile.value) mobileMenuOpen.value = false }
function toggleNavigation() { if (isMobile.value) mobileMenuOpen.value = !mobileMenuOpen.value; else isCollapse.value = !isCollapse.value }
function onMenuSelect() { if (isMobile.value) mobileMenuOpen.value = false }
function focusSearch() { nextTick(() => searchInput.value?.focus()) }
function goSearch(path: string) { searchOpen.value = false; searchText.value = ''; router.push(path) }
function onShortcut(event: KeyboardEvent) { if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') { event.preventDefault(); searchOpen.value = true } }
function handleUserCommand(command: string) { if (command === 'logout') { authStore.logout(); ElMessage.success('已退出登录'); router.push('/login') } else router.push(command === 'profile' ? '/profile' : '/notifications') }
onMounted(() => { updateViewport(); window.addEventListener('resize', updateViewport); window.addEventListener('keydown', onShortcut) })
onBeforeUnmount(() => { window.removeEventListener('resize', updateViewport); window.removeEventListener('keydown', onShortcut) })
</script>

<style scoped>
.layout-container{height:100vh}.content-shell{min-width:0}.sidebar{background:#fff;border-right:1px solid var(--app-border-base);transition:width .2s;display:flex;flex-direction:column;overflow:hidden}.logo{height:56px;display:flex;align-items:center;padding:0 16px;gap:10px;border-bottom:1px solid var(--app-border-base);flex:none}.logo-mark{display:grid;place-items:center;width:30px;height:30px;border-radius:8px;background:var(--app-accent);color:#fff;font-size:12px;font-weight:800;flex:none}.logo-copy{display:flex;flex-direction:column;white-space:nowrap;color:var(--app-text-primary);font-size:15px}.logo-copy small{font-size:9px;color:var(--app-text-secondary);letter-spacing:.3px}.menu-group-title{padding:18px 20px 6px;color:var(--app-text-placeholder);font-size:11px;font-weight:700;letter-spacing:1px}.nav-dot{width:6px;height:6px;border:1.5px solid currentColor;border-radius:50%;margin-right:12px;opacity:.7}:deep(.el-menu){border:0;overflow:auto;flex:1}:deep(.el-menu-item){height:38px;line-height:38px;margin:2px 8px;border-radius:7px;color:var(--app-text-regular)}:deep(.el-menu-item.is-active){background:var(--app-accent-light);color:var(--app-accent);font-weight:600}.sidebar-collapse{height:44px;border:0;border-top:1px solid var(--app-border-base);background:#fff;color:var(--app-text-secondary);display:flex;align-items:center;justify-content:center;gap:8px;cursor:pointer}.header{height:56px;display:flex;align-items:center;justify-content:space-between;background:#fff;border-bottom:1px solid var(--app-border-base);padding:0 24px}.header-left,.header-right,.user-info{display:flex;align-items:center}.header-right{gap:14px}.user-info{gap:8px;cursor:pointer;color:var(--app-text-regular)}.global-search{width:250px;height:32px;border:1px solid var(--app-border-base);border-radius:7px;background:var(--app-bg-page);color:var(--app-text-placeholder);display:flex;align-items:center;gap:8px;padding:0 10px;cursor:pointer}.global-search span{flex:1;text-align:left}.global-search kbd{border:1px solid var(--app-border-base);border-radius:4px;background:#fff;padding:1px 5px;font-size:10px}.main-content{background:var(--app-bg-page);padding:24px;overflow:auto}.search-results{display:grid;gap:6px;margin-top:14px;max-height:360px;overflow:auto}.search-results button{border:1px solid transparent;background:var(--app-bg-page);border-radius:7px;padding:11px 12px;display:flex;justify-content:space-between;cursor:pointer;color:var(--app-text-primary)}.search-results button:hover{border-color:var(--app-accent);background:var(--app-accent-light)}.search-results small{color:var(--app-text-placeholder)}.mobile-mask{display:none}@media(max-width:768px){.mobile-sidebar{position:fixed;inset:0 auto 0 0;z-index:2100;transform:translateX(-100%);box-shadow:var(--el-box-shadow-dark)}.mobile-sidebar.mobile-open{transform:translateX(0)}.mobile-mask{display:block;position:fixed;inset:0;z-index:2099;background:rgba(15,23,42,.42)}.header{padding:0 12px}.global-search{width:36px;padding:0;justify-content:center}.global-search span,.global-search kbd,.username,.breadcrumb :deep(.el-breadcrumb__item:not(:last-child)){display:none}.main-content{padding:12px;overflow-x:hidden}}
</style>
