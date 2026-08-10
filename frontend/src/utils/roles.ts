/**
 * 角色字典 —— RBAC 前端统一角色展示配置
 *
 * 角色值与后端 UserRole 枚举保持一致（全部小写）：
 * super_admin / admin / test_manager / tester / developer / auditor / viewer
 */

/** Element Plus el-tag 支持的 type 取值（空串表示默认主色） */
export type RoleTagType = 'danger' | 'warning' | 'success' | 'info' | ''

/** 角色 -> 中文标签 */
export const ROLE_LABELS: Record<string, string> = {
  super_admin: '超级管理员',
  admin: '系统管理员',
  test_manager: '测试经理',
  tester: '测试工程师',
  developer: '开发工程师',
  auditor: '审核员',
  viewer: '访客',
}

/** 角色 -> el-tag type */
export const ROLE_COLORS: Record<string, RoleTagType> = {
  super_admin: 'danger',
  admin: 'warning',
  test_manager: 'success',
  tester: '',
  developer: 'info',
  auditor: '',
  viewer: 'info',
}

/** 下拉选择用的角色选项列表（顺序即权限从高到低） */
export const ROLE_OPTIONS: Array<{ value: string; label: string }> = Object.keys(ROLE_LABELS).map(
  (value) => ({ value, label: ROLE_LABELS[value] })
)

/**
 * 获取角色中文名，未知角色回退为原始值。
 * @param role 角色枚举值
 */
export function roleLabel(role: string): string {
  return ROLE_LABELS[role] || role || '未知角色'
}

/**
 * 获取角色对应的 el-tag type，未知角色回退为 'info'。
 * @param role 角色枚举值
 */
export function roleTagType(role: string): RoleTagType {
  const hit = ROLE_COLORS[role]
  return hit === undefined ? 'info' : hit
}
