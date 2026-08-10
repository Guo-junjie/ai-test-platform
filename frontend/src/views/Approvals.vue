<template>
  <div class="approvals-page">
    <el-card shadow="hover">
      <template #header>
        <div class="card-header">
          <span>审核中心</span>
          <el-button :loading="loading" @click="loadRequests">
            <el-icon><Refresh /></el-icon>
            刷新
          </el-button>
        </div>
      </template>

      <el-alert
        title="待审批的变更申请"
        description="管理员发起的新建用户、删除用户、修改角色等敏感操作需在此审批。通过后立即生效，驳回需填写理由。"
        type="info"
        :closable="false"
        style="margin-bottom: 16px;"
      />

      <el-table :data="requests" v-loading="loading" style="width: 100%">
        <el-table-column label="类型" width="130">
          <template #default="{ row }">
            <el-tag :type="typeTagType(row.type)" size="small">
              {{ row.type_label || typeLabel(row.type) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="申请人" min-width="140">
          <template #default="{ row }">
            {{ row.requester_name || row.requester || row.created_by || '-' }}
          </template>
        </el-table-column>
        <el-table-column label="目标 / 拟设角色" min-width="240">
          <template #default="{ row }">
            {{ targetText(row) }}
          </template>
        </el-table-column>
        <el-table-column label="提交时间" width="180">
          <template #default="{ row }">
            {{ formatTime(row.created_at) }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="180" fixed="right">
          <template #default="{ row }">
            <el-button
              size="small"
              type="success"
              plain
              :loading="handlingId === row.id"
              @click="handleApprove(row)"
            >
              通过
            </el-button>
            <el-button
              size="small"
              type="danger"
              plain
              :loading="handlingId === row.id"
              @click="handleReject(row)"
            >
              驳回
            </el-button>
          </template>
        </el-table-column>

        <template #empty>
          <el-empty description="暂无待审批的变更申请" />
        </template>
      </el-table>
    </el-card>
  </div>
</template>

<script setup lang="ts">
/**
 * 审核中心（审核员 / 超级管理员可见）。
 *
 * 展示状态为 pending 的变更申请，支持通过与驳回（驳回需填理由）。
 */
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import { changeRequestApi } from '@/api'
import { roleLabel } from '@/utils/roles'

const requests = ref<any[]>([])
const loading = ref<boolean>(false)
const handlingId = ref<string>('')

/** 变更类型 -> 中文标签 */
const TYPE_LABELS: Record<string, string> = {
  create_user: '新建用户',
  delete_user: '删除用户',
  change_role: '修改角色',
}

/** 变更类型 -> el-tag type */
const TYPE_COLORS: Record<string, 'success' | 'danger' | 'warning' | 'info'> = {
  create_user: 'success',
  delete_user: 'danger',
  change_role: 'warning',
}

/** 类型中文名，兼容后端直接下发 type_label 的情况 */
function typeLabel(type: string): string {
  return TYPE_LABELS[type] || type || '未知类型'
}

function typeTagType(type: string): 'success' | 'danger' | 'warning' | 'info' {
  return TYPE_COLORS[type] || 'info'
}

/**
 * 拼装「目标 / 拟设角色」列文案。
 * 兼容后端把详情放在 payload / detail / target_* 等不同字段的情况。
 */
function targetText(row: any): string {
  const payload = row?.payload ?? row?.detail ?? row ?? {}
  const target = row?.target_name || row?.target_username || payload?.username || ''
  const nextRole = row?.target_role || payload?.role || ''
  const parts: string[] = []
  if (target) parts.push(String(target))
  if (nextRole) parts.push(`拟设角色：${roleLabel(String(nextRole))}`)
  return parts.length > 0 ? parts.join(' · ') : '-'
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
function pickList(res: any): any[] {
  if (Array.isArray(res)) return res
  const d = res?.data ?? res ?? {}
  if (Array.isArray(d)) return d
  return d.list || d.items || d.requests || []
}

/** 加载待审批列表 */
async function loadRequests(): Promise<void> {
  loading.value = true
  try {
    const res: any = await changeRequestApi.list({ status: 'pending' })
    requests.value = pickList(res)
  } catch {
    requests.value = []
  } finally {
    loading.value = false
  }
}

/** 审批通过 */
async function handleApprove(row: any): Promise<void> {
  try {
    await ElMessageBox.confirm(
      `确认通过该「${typeLabel(row.type)}」申请吗？通过后立即生效。`,
      '审批确认',
      { type: 'warning', confirmButtonText: '通过', cancelButtonText: '取消' }
    )
  } catch {
    return // 用户取消
  }

  handlingId.value = row.id
  try {
    await changeRequestApi.approve(row.id)
    ElMessage.success('已通过该申请')
    await loadRequests()
  } catch (e: any) {
    ElMessage.error(e?.message || '审批失败')
  } finally {
    handlingId.value = ''
  }
}

/** 审批驳回（需填写理由） */
async function handleReject(row: any): Promise<void> {
  let note = ''
  try {
    const result = await ElMessageBox.prompt('请输入驳回理由', '驳回申请', {
      confirmButtonText: '确认驳回',
      cancelButtonText: '取消',
      inputPlaceholder: '例如：角色权限过高，请重新评估',
      inputValidator: (val: string) => (val && val.trim().length > 0 ? true : '驳回理由不能为空'),
    })
    note = String(result.value || '').trim()
  } catch {
    return // 用户取消
  }

  handlingId.value = row.id
  try {
    await changeRequestApi.reject(row.id, { note })
    ElMessage.success('已驳回该申请')
    await loadRequests()
  } catch (e: any) {
    ElMessage.error(e?.message || '驳回失败')
  } finally {
    handlingId.value = ''
  }
}

onMounted(loadRequests)
</script>

<style scoped>
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
</style>
