/**
 * 界面风格（变体）偏好的唯一真相源
 * -----------------------------------------------------------------------------
 * 为什么存在：
 *   历史上这个「默认变体」在 main.ts 与 UiVariantSwitch.vue 里各写了一份，
 *   且切换器在首访（localStorage 为空）时会把这份手写的默认值回写落盘，
 *   于是「默认值」被当成了「用户选择」——首访渲染 v3，落盘却成 v1，
 *   第二次刷新即丢回 v1。根因就是同一个默认值分散在两处、各写一份。
 *
 *   因此把「键名 / 候选值 / 默认值 / 类型守卫 / 读取 / 写入 / 应用」全部收敛到本文件，
 *   任何需要读写变体偏好的地方都必须从这里取值，禁止各自再写一份默认值。
 *
 * 约束：纯偏好设置，不含任何业务逻辑；所有 localStorage 访问均以 try/catch 兜底，
 *       在隐私模式 / 存储被禁用 / WebView 限制等场景下静默降级，绝不抛异常打断应用启动。
 */

/** 变体偏好的存储键名 */
export const UI_VARIANT_KEY = 'ui-variant'

/** 所有合法变体（顺序即切换器中的展示顺序） */
export const UI_VARIANTS = ['v1', 'v2', 'v3'] as const

/** 变体类型：由候选值数组推导，新增变体只需改 UI_VARIANTS */
export type UiVariant = (typeof UI_VARIANTS)[number]

/** 默认变体：v3「紧凑专业」（用户拍板选定） */
export const DEFAULT_UI_VARIANT: UiVariant = 'v3'

/** 类型守卫：判断任意值是否为合法变体 */
export function isUiVariant(value: unknown): value is UiVariant {
  return typeof value === 'string' && (UI_VARIANTS as readonly string[]).includes(value)
}

/**
 * 读取已存储的变体偏好。
 * 存储不可用或值非法时，一律返回 DEFAULT_UI_VARIANT；
 * 注意：这里**只读不写**——默认值不应被当作「用户选择」落盘。
 */
export function readStoredUiVariant(): UiVariant {
  try {
    const raw = localStorage.getItem(UI_VARIANT_KEY)
    return isUiVariant(raw) ? raw : DEFAULT_UI_VARIANT
  } catch {
    return DEFAULT_UI_VARIANT
  }
}

/**
 * 写入变体偏好。仅在用户显式选择时调用；写入失败静默忽略
 * （本次会话内仍靠 applyUiVariant 设置的 dataset 生效）。
 */
export function writeStoredUiVariant(v: UiVariant): void {
  try {
    localStorage.setItem(UI_VARIANT_KEY, v)
  } catch {
    /* 存储不可用（隐私模式 / 配额满 / 被策略禁用）：忽略，不影响本次会话 */
  }
}

/** 将变体应用到 <html data-ui-variant>，由 styles/theme.css 承接对应令牌 */
export function applyUiVariant(v: UiVariant): void {
  document.documentElement.dataset.uiVariant = v
}
