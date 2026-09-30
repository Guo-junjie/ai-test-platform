export type NavIcon =
  | 'home' | 'folder' | 'spark' | 'layers' | 'code'
  | 'play' | 'flow' | 'clock' | 'list'
  | 'report' | 'analytics' | 'target' | 'trend' | 'bug' | 'gate'
  | 'book' | 'chat' | 'doc' | 'cube' | 'git' | 'db'
  | 'cpu' | 'settings' | 'users' | 'scroll'

export type NavItem = {
  label: string
  path: string
  icon: NavIcon
  admin?: boolean
  audit?: boolean
}
export type NavGroup = { title?: string; lock?: string; items: NavItem[] }

/** 与交互原型一致的信息架构；路由、全局搜索和面包屑共用这一份数据。 */
export const NAV_GROUPS: NavGroup[] = [
  { items: [{ label: '工作台', path: '/dashboard', icon: 'home' }, { label: '项目', path: '/projects', icon: 'folder' }] },
  { title: '测试资产', items: [{ label: '智能用例生成', path: '/case-generation', icon: 'spark' }, { label: '用例管理与评审', path: '/case-library', icon: 'layers' }, { label: '脚本生成', path: '/scripts', icon: 'code' }] },
  { title: '测试执行', items: [{ label: 'API 计划执行', path: '/test-run', icon: 'play' }, { label: '场景编排', path: '/scenario', icon: 'flow' }, { label: '定时任务', path: '/scheduled-tasks', icon: 'clock' }, { label: '执行记录', path: '/runs', icon: 'list' }] },
  { title: '质量分析', items: [{ label: '测试报告', path: '/report', icon: 'report' }, { label: '报告分析', path: '/report-analysis', icon: 'analytics' }, { label: '代码覆盖率', path: '/coverage', icon: 'target' }, { label: '质量趋势', path: '/quality-trend', icon: 'trend' }, { label: '缺陷中心', path: '/defects', icon: 'bug' }, { label: '质量门禁', path: '/settings/quality-gate', icon: 'gate' }] },
  { title: '知识中心', items: [{ label: '知识库', path: '/knowledge', icon: 'book' }, { label: '知识问答', path: '/knowledge-qa', icon: 'chat' }] },
  { title: '集成与配置', items: [{ label: '接口文档评审', path: '/doc-review', icon: 'doc' }, { label: '代码解析', path: '/analysis', icon: 'cube', admin: true }, { label: '仓库配置', path: '/sources', icon: 'git', admin: true }, { label: '数据库连接', path: '/database-manage', icon: 'db' }] },
  { title: '系统管理', lock: '管理员', items: [{ label: 'AI 模型配置', path: '/settings/models', icon: 'cpu', admin: true }, { label: '基础配置', path: '/settings', icon: 'settings', admin: true }, { label: '用户管理', path: '/user-management', icon: 'users', admin: true }, { label: '审计日志', path: '/settings/audit', icon: 'scroll', audit: true }] },
]

export const NAV_ITEMS = NAV_GROUPS.flatMap(group => group.items)
