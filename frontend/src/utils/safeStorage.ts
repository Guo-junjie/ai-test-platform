/**
 * localStorage 安全访问封装
 *
 * 用途：浏览器隐私模式、存储配额已满、禁用第三方 Cookie 等场景下，
 * 直接读写 localStorage 会抛出 SecurityError / QuotaExceededError，
 * 若未兜底会导致整个应用白屏。
 *
 * 约束：
 * - 纯工具模块，不引入任何外部依赖；
 * - 所有访问以 try/catch 兜底，失败时降级为「内存态 + 返回空」，不向上抛错；
 * - 仅封装存储访问，不改变任何业务分支与逻辑。
 */

const memoryFallback = new Map<string, string>()

export function safeGetItem(key: string): string | null {
  try {
    return window.localStorage.getItem(key)
  } catch {
    return memoryFallback.get(key) ?? null
  }
}

export function safeSetItem(key: string, value: string): void {
  try {
    window.localStorage.setItem(key, value)
  } catch {
    // 隐私模式 / 配额满：降级到内存态，保证本次会话内可读写
    memoryFallback.set(key, value)
  }
}

export function safeRemoveItem(key: string): void {
  try {
    window.localStorage.removeItem(key)
  } catch {
    memoryFallback.delete(key)
  }
}
