<template>
  <!-- 公开路由（登录页）不套 Layout，避免展示侧边栏/顶栏等功能区 -->
  <router-view v-if="isPublic" />
  <Layout v-else />
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import Layout from '@/components/Layout.vue'

const route = useRoute()
/** 是否为公开路由（如登录页）：未登录不展示任何功能栏 */
const isPublic = computed<boolean>(() => !!route.meta?.public)
</script>

<style>
/* 只保留必要的重置；字体栈、盒模型等一律交给 styles/theme.css 统一维护 */
html,
body,
#app {
  height: 100%;
}

@media (max-width: 768px) {
  .el-dialog { --el-dialog-width: calc(100vw - 24px); margin-top: 5vh; }
  .el-drawer { max-width: 94vw; }
  .main-content .el-card__body { overflow-x: auto; }
  .main-content .el-card__body > .el-table { min-width: 680px; }
  .el-form-item { align-items: flex-start; }
}
</style>
