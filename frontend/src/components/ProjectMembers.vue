<template>
  <el-button v-if="canManage" @click="open">项目成员</el-button>
  <el-dialog v-model="visible" title="项目成员与权限" width="600px" destroy-on-close>
    <el-alert title="仅负责人、管理员和已授权成员可访问项目。全局只读角色始终不能修改或执行测试。" type="info" :closable="false" />
    <el-form :inline="true" style="margin-top: 16px" @submit.prevent="save">
      <el-form-item label="用户名"><el-input v-model="username" placeholder="填写已有账号" /></el-form-item>
      <el-form-item label="项目权限"><el-select v-model="access" style="width: 110px"><el-option label="只读" value="read" /><el-option label="读写" value="write" /></el-select></el-form-item>
      <el-button type="primary" :disabled="!username.trim()" :loading="saving" @click="save">添加 / 更新</el-button>
    </el-form>
    <el-table :data="members" v-loading="loading">
      <el-table-column prop="username" label="用户名" />
      <el-table-column label="权限"><template #default="{ row }">{{ row.access === 'write' ? '读写' : '只读' }}</template></el-table-column>
      <el-table-column label="状态"><template #default="{ row }">{{ row.is_active ? '已启用' : '已停用' }}</template></el-table-column>
      <el-table-column label="操作" width="90"><template #default="{ row }"><el-button link type="danger" @click="remove(row)">撤销</el-button></template></el-table-column>
    </el-table>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { projectApi } from '@/api'
import { useAuthStore } from '@/stores'

const props = defineProps<{ projectId: string; ownerId?: string }>()
const auth = useAuthStore()
const canManage = computed(() => auth.isAdmin || auth.user?.id === props.ownerId)
type Member = { user_id: string; username: string; access: 'read' | 'write'; is_active: boolean }
const members = ref<Member[]>([])
const visible = ref(false)
const loading = ref(false)
const saving = ref(false)
const username = ref('')
const access = ref<'read' | 'write'>('read')
async function load() {
  loading.value = true
  try {
    const response = await projectApi.members(props.projectId)
    members.value = response.data.items
  } finally { loading.value = false }
}
async function open() { visible.value = true; await load() }
async function save() {
  saving.value = true
  try {
    await projectApi.setMember(props.projectId, { username: username.value.trim(), access: access.value })
    username.value = ''
    ElMessage.success('项目权限已保存')
    await load()
  } finally { saving.value = false }
}
async function remove(member: Member) {
  try { await ElMessageBox.confirm(`撤销 ${member.username} 的项目访问权限？`, '撤销成员') } catch { return }
  await projectApi.removeMember(props.projectId, member.user_id)
  await load()
}
</script>
