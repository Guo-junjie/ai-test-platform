<template>
  <div class="user-management-page">
    <el-card shadow="hover">
      <template #header>
        <div class="card-header">
          <span>用户管理</span>
          <div class="header-actions">
            <el-button type="primary" @click="openCreateDialog">
              <el-icon><Plus /></el-icon>
              新建用户
            </el-button>
            <el-button :loading="loading" @click="loadUsers">
              <el-icon><Refresh /></el-icon>
              刷新
            </el-button>
          </div>
        </div>
      </template>

      <el-alert
        title="基于角色的访问控制（RBAC）"
        description="管理员可在此新建用户、分配角色与启停账号。新建用户、删除用户、修改角色等敏感操作可能需要审核员审批后才会生效。"
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
              {{ roleLabel(row.role) }}
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
        <el-table-column label="操作" min-width="330">
          <template #default="{ row }">
            <el-select
              :model-value="row.role"
              size="small"
              style="width: 130px;"
              :disabled="updatingId === row.id"
              @change="(val: string) => handleRoleChange(row, val)"
            >
              <el-option
                v-for="opt in ROLE_OPTIONS"
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
            <el-button
              size="small"
              plain
              type="danger"
              :loading="deletingId === row.id"
              @click="handleDelete(row)"
            >
              删除
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

    <!-- 新建用户对话框 -->
    <el-dialog v-model="createDialogVisible" title="新建用户" width="480px" destroy-on-close>
      <el-form
        ref="createFormRef"
        :model="createForm"
        :rules="createRules"
        label-width="90px"
        @submit.prevent="submitCreate"
      >
        <el-form-item label="用户名" prop="username">
          <el-input v-model="createForm.username" placeholder="请输入用户名" clearable />
        </el-form-item>
        <el-form-item label="邮箱" prop="email">
          <el-input v-model="createForm.email" placeholder="请输入邮箱" clearable />
        </el-form-item>
        <el-form-item label="密码" prop="password">
          <el-input
            v-model="createForm.password"
            type="password"
            placeholder="至少 6 位"
            show-password
            autocomplete="new-password"
          />
        </el-form-item>
        <el-form-item label="角色" prop="role">
          <el-select v-model="createForm.role" placeholder="请选择角色" style="width: 100%;">
            <el-option
              v-for="opt in ROLE_OPTIONS"
              :key="opt.value"
              :label="opt.label"
              :value="opt.value"
            />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="submitCreate">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
/**
 * 用户管理页（仅管理员可访问）。
 *
 * 支持：新建用户、修改角色、启停账号、删除用户。
 * 其中新建 / 改角色 / 删除三类敏感操作，后端可能返回 data.status === 'pending'
 * 表示已进入审核流，此时前端提示「已提交审核，待审核员审批」且不做本地乐观更新。
 */
import { ref, reactive, onMounted } from 'vue'
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from 'element-plus'
import { Plus, Refresh } from '@element-plus/icons-vue'
import { authApi } from '@/api'
import { ROLE_OPTIONS, roleLabel, roleTagType } from '@/utils/roles'

const users = ref<any[]>([])
const loading = ref<boolean>(false)
const updatingId = ref<string>('')
const statusUpdatingId = ref<string>('')
const deletingId = ref<string>('')
const total = ref<number>(0)
const page = ref<number>(1)
const pageSize = ref<number>(50)

/** 新建用户对话框 */
const createDialogVisible = ref<boolean>(false)
const creating = ref<boolean>(false)
const createFormRef = ref<FormInstance>()
const createForm = reactive({
  username: '',
  email: '',
  password: '',
  role: 'tester',
})

const createRules: FormRules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  email: [
    { required: true, message: '请输入邮箱', trigger: 'blur' },
    { type: 'email', message: '邮箱格式不正确', trigger: 'blur' },
  ],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 6, message: '密码长度至少 6 位', trigger: 'blur' },
  ],
  role: [{ required: true, message: '请选择角色', trigger: 'change' }],
}

/** 判断后端响应是否表示「已提交审核」 */
function isPending(res: any): boolean {
  const d = res?.data ?? res ?? {}
  return d?.status === 'pending'
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

/** 打开新建用户对话框并重置表单 */
function openCreateDialog(): void {
  createForm.username = ''
  createForm.email = ''
  createForm.password = ''
  createForm.role = 'tester'
  createDialogVisible.value = true
}

/** 提交新建用户 */
async function submitCreate(): Promise<void> {
  if (!createFormRef.value) return
  const valid = await createFormRef.value.validate().catch(() => false)
  if (!valid) return

  creating.value = true
  try {
    const res: any = await authApi.register({
      username: createForm.username,
      email: createForm.email,
      password: createForm.password,
      role: createForm.role,
    })
    if (isPending(res)) {
      ElMessage.success('已提交审核，待审核员审批')
    } else {
      ElMessage.success('用户创建成功')
    }
    createDialogVisible.value = false
    await loadUsers()
  } catch (e: any) {
    ElMessage.error(e?.message || '用户创建失败')
  } finally {
    creating.value = false
  }
}

/** 修改用户角色 */
async function handleRoleChange(row: any, newRole: string): Promise<void> {
  if (!newRole || newRole === row.role) return
  const oldRole = row.role
  updatingId.value = row.id
  try {
    const res: any = await authApi.updateRole(row.id, newRole)
    if (isPending(res)) {
      // 进入审核流：不做本地乐观更新，等待审批通过后再生效
      row.role = oldRole
      ElMessage.success('已提交审核，待审核员审批')
    } else {
      row.role = newRole
      ElMessage.success(`已将 ${row.username} 的角色修改为「${roleLabel(newRole)}」`)
    }
  } catch (e: any) {
    row.role = oldRole // 失败回滚
    ElMessage.error(e?.message || '角色修改失败')
  } finally {
    updatingId.value = ''
  }
}

/** 启用 / 禁用用户（立即生效，不走审核流） */
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

/** 删除用户（二次确认） */
async function handleDelete(row: any): Promise<void> {
  try {
    await ElMessageBox.confirm(
      `确认删除用户「${row.username}」吗？该操作不可恢复。`,
      '删除确认',
      {
        type: 'warning',
        confirmButtonText: '删除',
        confirmButtonClass: 'el-button--danger',
        cancelButtonText: '取消',
      }
    )
  } catch {
    return // 用户取消
  }

  deletingId.value = row.id
  try {
    const res: any = await authApi.deleteUser(row.id)
    if (isPending(res)) {
      ElMessage.success('已提交审核，待审核员审批')
    } else {
      ElMessage.success(`已删除用户 ${row.username}`)
    }
    await loadUsers()
  } catch (e: any) {
    ElMessage.error(e?.message || '删除失败')
  } finally {
    deletingId.value = ''
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

.header-actions {
  display: flex;
  gap: 8px;
}
</style>
