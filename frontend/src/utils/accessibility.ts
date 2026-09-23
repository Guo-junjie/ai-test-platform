/**
 * 为动态渲染的 Element Plus 控件补齐可访问名称。
 *
 * 优先使用表单项标签，其次使用 placeholder/name/title。业务组件显式提供的
 * aria-label / aria-labelledby 始终优先，不会被覆盖。
 */
function visibleText(element: Element): string {
  return (element.textContent || '').replace(/\s+/g, ' ').trim()
}

function labelFor(element: HTMLElement): string {
  const formItem = element.closest('.el-form-item')
  const formLabel = formItem?.querySelector('.el-form-item__label')
  const candidate = visibleText(formLabel || document.createElement('span'))
  if (candidate) return candidate.replace(/[：:]$/, '')

  return (
    element.getAttribute('placeholder')
    || element.getAttribute('name')
    || element.getAttribute('title')
    || ''
  ).trim()
}

function needsAccessibleName(element: HTMLElement): boolean {
  if (!element.matches('input, textarea, button, [role="button"]')) return false
  if (element.hasAttribute('aria-label') || element.hasAttribute('aria-labelledby')) return false
  if (element.id && document.querySelector(`label[for="${CSS.escape(element.id)}"]`)) return false
  if (element.closest('label')) return false
  if (element.tagName === 'BUTTON' && visibleText(element)) return false
  return true
}

function applyAccessibleNames(root: ParentNode = document): void {
  root.querySelectorAll<HTMLElement>('input, textarea, button, [role="button"]')
    .forEach((element) => {
      if (!needsAccessibleName(element)) return
      const label = labelFor(element)
      if (label) element.setAttribute('aria-label', label)
    })
}

export function installAccessibilityNames(): () => void {
  applyAccessibleNames()
  const observer = new MutationObserver((mutations) => {
    for (const mutation of mutations) {
      mutation.addedNodes.forEach((node) => {
        if (node instanceof HTMLElement) {
          if (needsAccessibleName(node)) {
            const label = labelFor(node)
            if (label) node.setAttribute('aria-label', label)
          }
          applyAccessibleNames(node)
        }
      })
    }
  })
  observer.observe(document.body, { childList: true, subtree: true })
  return () => observer.disconnect()
}
