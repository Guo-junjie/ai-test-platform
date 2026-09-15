import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import 'element-plus/dist/index.css'

/* 全局设计令牌层：必须在 element-plus 样式之后引入，才能覆盖其 CSS 变量 */
import '@/styles/theme.css'

import * as ElementPlusIconsVue from '@element-plus/icons-vue'

import App from './App.vue'
import router from './router'

/**
 * 视觉方向（变体）：v1 清透白 / v2 深空 / v3 紧凑专业
 * 仅影响样式令牌，不影响任何业务逻辑；缺省 v3。
 */
const UI_VARIANT_KEY = 'ui-variant'
const UI_VARIANT_WHITELIST = new Set(['v1', 'v2', 'v3'])
const storedVariant = localStorage.getItem(UI_VARIANT_KEY)
const variant =
  storedVariant && UI_VARIANT_WHITELIST.has(storedVariant) ? storedVariant : 'v3'
document.documentElement.dataset.uiVariant = variant

const app = createApp(App)

// 注册 Element Plus 图标
for (const [key, component] of Object.entries(ElementPlusIconsVue)) {
  app.component(key, component)
}

app.use(createPinia())
app.use(router)
// 中文语言包：统一组件内置文案（表格空态、分页、日期选择器等）
app.use(ElementPlus, { locale: zhCn })

app.mount('#app')
