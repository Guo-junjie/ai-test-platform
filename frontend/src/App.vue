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
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

html, body, #app {
  height: 100%;
  font-family: 'Helvetica Neue', Helvetica, 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', sans-serif;
}
</style>
