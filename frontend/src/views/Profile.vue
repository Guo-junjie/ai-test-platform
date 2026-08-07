<template>
  <div class="profile-page">
    <el-card shadow="hover">
      <template #header>个人设置</template>
      <ProfileSettings />
    </el-card>
  </div>
</template>

<script setup lang="ts">
/** 个人设置页：所有登录用户均可访问，用于修改个人信息与密码。 */
import ProfileSettings from '@/components/ProfileSettings.vue'
</script>
