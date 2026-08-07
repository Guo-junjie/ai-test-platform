<template>
  <div class="user-management-page">
    <el-card shadow="hover">
      <template #header>
        <div class="card-header">
          <span>用户管理</span>
          <el-button :loading="loading" @click="loadUsers">
            <el-icon><Refresh /></el-icon>
            刷新
          </el-button>
        </div>
      </template>

      <el-alert
        title="基于角色的访问控制（RBAC）"
        description="管理员可在此为用户分配角色。管理员：全部权限；测试工程师：可创建/执行测试任务；开发者：可查看报告与缺陷；访客：只读。"
        type="info"
        :closable="false"
        style="margin-bottom: 16px;"
      />

      <el-table :data="users" v-loading="loading" style="width: 100%">
        <el-table-column prop="username" label="用户名" min-width="140" />
        <el-table-column prop="email" label="邮箱" min-width="200" show-overflow-tooltip />
        <el-table-column label="角色" width="130">
          <template #default="{ row }">
            <el-tag :type="roleTagType(row.role)" size="small">
              {{ roleLabels[row.role] || row.role }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="row.is_active ? 'success' : 'info'" size="small">
              {{ row.is_active ? '启用' : '禁用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="创建时间" width="180">
          <template #default="{ row }">
            {{ formatTime(row.created_at) }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="280">
          <template #default="{ row }">
            <el-select
              :model-value="row.role"
              size="small"
              style="width: 130px;"
              :disabled="updatingId === row.id"
              @change="(val: string) => handleRoleChange(row, val)"
            >
              <el-option
                v-for="opt in roleOptions"
                :key="opt.value"
                :label="opt.label"
                :value="opt.value"
              />
            </el-select>
            <el-button
              size="small"
              plain
              style="margin-left: 8px;"
              :type="row.is_active ? 'warning' : 'success'"
              :loading="statusUpdatingId === row.id"
              @click="handleToggleStatus(row)"
            >
              {{ row.is_active ? '禁用' : '启用' }}
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <el-pagination
        v-if="total > pageSize"
        background
        layout="prev, pager, next, total"
        :total="total"
        :page-size="pageSize"
        v-model:current-page="page"
        style="margin-top: 16px; justify-content: flex-end;"
        @current-change="loadUsers"
      />
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { authApi } from '@/api'

/** 角色枚举值（与后端 UserRole 保持一致，为小写） -> 中文标签 */
const roleLabels: Record<string, string> = {
  admin: '管理员',
  tester: '测试工程师',
  developer: '开发者',
  viewer: '访客',
}

const roleOptions = [
  { value: 'admin', label: '管理员' },
  { value: 'tester', label: '测试工程师' },
  { value: 'developer', label: '开发者' },
  { value: 'viewer', label: '访客' },
]

const users = ref<any[]>([])
const loading = ref(false)
const updatingId = ref<string>('')
const statusUpdatingId = ref<string>('')
const total = ref(0)
const page = ref(1)
const pageSize = ref(50)

/** 角色对应的 tag 颜色 */
function roleTagType(role: string): 'danger' | 'success' | 'primary' | 'info' {
  const map: Record<string, 'danger' | 'success' | 'primary' | 'info'> = {
    admin: 'danger',
    tester: 'success',
    developer: 'primary',
    viewer: 'info',
  }
  return map[role] || 'info'
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

/** 兼容后端返回 {code,data:{list,total}} 或裸数组 */
function pickList(res: any): { list: any[]; total: number } {
  if (Array.isArray(res)) return { list: res, total: res.length }
  const d = res?.data ?? res ?? {}
  if (Array.isArray(d)) return { list: d, total: d.length }
  const list = d.list || d.items || d.users || []
  return { list, total: d.total ?? list.length }
}

/** 加载用户列表 */
async function loadUsers(): Promise<void> {
  loading.value = true
  try {
    const res: any = await authApi.listUsers({ page: page.value, page_size: pageSize.value })
    const picked = pickList(res)
    users.value = picked.list
    total.value = picked.total
  } catch {
    users.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

/** 修改用户角色 */
async function handleRoleChange(row: any, newRole: string): Promise<void> {
  if (!newRole || newRole === row.role) return
  const oldRole = row.role
  updatingId.value = row.id
  try {
    await authApi.updateRole(row.id, newRole)
    row.role = newRole
    ElMessage.success(`已将 ${row.username} 的角色修改为「${roleLabels[newRole] || newRole}」`)
  } catch (e: any) {
    row.role = oldRole // 失败回滚
    ElMessage.error(e?.message || '角色修改失败')
  } finally {
    updatingId.value = ''
  }
}

/** 启用 / 禁用用户 */
async function handleToggleStatus(row: any): Promise<void> {
  const nextActive = !row.is_active
  const actionText = nextActive ? '启用' : '禁用'
  try {
    await ElMessageBox.confirm(`确认${actionText}用户「${row.username}」吗？`, `${actionText}确认`, {
      type: 'warning',
      confirmButtonText: actionText,
      cancelButtonText: '取消',
    })
  } catch {
    return // 用户取消
  }

  statusUpdatingId.value = row.id
  try {
    await authApi.updateStatus(row.id, nextActive)
    row.is_active = nextActive
    ElMessage.success(`已${actionText}用户 ${row.username}`)
  } catch (e: any) {
    ElMessage.error(e?.message || `${actionText}失败，后端可能暂未提供该接口`)
  } finally {
    statusUpdatingId.value = ''
  }
}

onMounted(loadUsers)
</script>

<style scoped>
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
</style>
