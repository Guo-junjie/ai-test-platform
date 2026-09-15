/**
 * 图表色板（canvas 渲染专用）
 * -----------------------------------------------------------------------------
 * ECharts / SVG 字符串等 canvas 场景**不走 DOM 样式解析**，CSS 变量（var(--x)）
 * 在其中不是合法颜色值。因此这里在运行时从 :root 读取设计令牌的计算值，
 * 供 ECharts 配置使用，保证 v1/v2/v3 变体切换后图表配色与全站一致。
 *
 * 使用 getter（而非静态常量）：每次读取都重新取计算值，
 * 切变体后重新 setOption 即可拿到新色，无需刷新页面。
 */

/** 从 documentElement 读取某个设计令牌的计算值（SSR 安全） */
export function readToken(name: string): string {
  if (typeof window === 'undefined') return ''
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || ''
}

/** 图表通用色板：跟随 v1/v2/v3 变体自动变化 */
export const CHART_COLORS = {
  get primary() {
    return readToken('--el-color-primary')
  },
  get success() {
    return readToken('--el-color-success')
  },
  get warning() {
    return readToken('--el-color-warning')
  },
  get danger() {
    return readToken('--el-color-danger')
  },
  get info() {
    return readToken('--el-color-info')
  },
  get textPrimary() {
    return readToken('--app-text-primary')
  },
  get textRegular() {
    return readToken('--app-text-regular')
  },
  get textSecondary() {
    return readToken('--app-text-secondary')
  },
  get textPlaceholder() {
    return readToken('--app-text-placeholder')
  },
  get border() {
    return readToken('--app-border-light')
  },
  get fillLighter() {
    return readToken('--el-fill-color-lighter')
  },
  get cardBg() {
    return readToken('--app-bg-card')
  },
}

/** 多系列折线/柱状的默认顺序色板（6 色） */
export const CHART_SERIES: string[] = [
  CHART_COLORS.primary,
  CHART_COLORS.success,
  CHART_COLORS.warning,
  CHART_COLORS.danger,
  CHART_COLORS.info,
  CHART_COLORS.textSecondary,
]
