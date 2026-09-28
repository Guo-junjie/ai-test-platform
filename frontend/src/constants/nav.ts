export type NavItem = { label: string; path: string; admin?: boolean; audit?: boolean }
export type NavGroup = { title?: string; items: NavItem[] }

/** 与交互原型一致的信息架构；路由、全局搜索和面包屑共用这一份数据。 */
export const NAV_GROUPS: NavGroup[] = [
  { items: [{ label: '工作台', path: '/dashboard' }, { label: '项目', path: '/projects' }] },
  { title: '测试资产', items: [{ label: '智能用例生成', path: '/case-generation' }, { label: '用例管理与评审', path: '/case-library' }, { label: '脚本生成', path: '/scripts' }] },
  { title: '测试执行', items: [{ label: 'API 计划执行', path: '/test-run' }, { label: '场景编排', path: '/scenario' }, { label: '定时任务', path: '/scheduled-tasks' }, { label: '执行记录', path: '/runs' }] },
  { title: '质量分析', items: [{ label: '测试报告', path: '/report' }, { label: '报告分析', path: '/report-analysis' }, { label: '代码覆盖率', path: '/coverage' }, { label: '质量趋势', path: '/quality-trend' }, { label: '缺陷中心', path: '/defects' }, { label: '质量门禁', path: '/settings/quality-gate' }] },
  { title: '知识中心', items: [{ label: '知识库', path: '/knowledge' }, { label: '知识问答', path: '/knowledge-qa' }] },
  { title: '集成与配置', items: [{ label: '接口文档评审', path: '/doc-review' }, { label: '代码解析', path: '/analysis', admin: true }, { label: '仓库配置', path: '/sources', admin: true }, { label: '数据库连接', path: '/database-manage' }] },
  { title: '系统管理', items: [{ label: 'AI 模型配置', path: '/settings/models', admin: true }, { label: '基础配置', path: '/settings', admin: true }, { label: '用户管理', path: '/user-management', admin: true }, { label: '审计日志', path: '/settings/audit', audit: true }] },
]

export const NAV_ITEMS = NAV_GROUPS.flatMap(group => group.items)
