<template>
  <!--
    界面风格切换器（纯偏好设置，无任何业务接口调用）。
    仅影响视觉令牌：写入 localStorage['ui-variant'] 并同步 <html data-ui-variant>，
    由 styles/theme.css 承接不同变体，无需刷新页面。
  -->
  <el-popover
    placement="bottom-end"
    :width="230"
    trigger="click"
    popper-class="ui-variant-popper"
  >
    <template #reference>
      <button type="button" class="ui-variant-trigger" :title="`界面风格：${currentLabel}`">
        <el-icon class="ui-variant-trigger__icon"><Brush /></el-icon>
        <span class="ui-variant-trigger__text">界面风格</span>
      </button>
    </template>

    <div class="ui-variant-list">
      <div class="ui-variant-list__title">界面风格</div>
      <div
        v-for="opt in options"
        :key="opt.value"
        class="ui-variant-option"
        :class="{ 'is-active': opt.value === current }"
        @click="select(opt.value)"
      >
        <span
          class="ui-variant-option__swatch"
          :style="{ background: opt.swatch, borderColor: opt.swatchBorder }"
        ></span>
        <span class="ui-variant-option__body">
          <span class="ui-variant-option__name">{{ opt.label }}</span>
          <span class="ui-variant-option__desc">{{ opt.desc }}</span>
        </span>
        <el-icon v-if="opt.value === current" class="ui-variant-option__check"><Check /></el-icon>
      </div>
    </div>
  </el-popover>
</template>

<script setup lang="ts">
/**
 * UiVariantSwitch —— 仅做视觉方向偏好切换，属于展示型组件。
 *
 * 约束：不引入任何业务接口 / store / 路由逻辑；
 *       读写变体偏好一律走 @/styles/uiVariant 这个唯一真相源，
 *       组件自身不再持有任何默认值或存储键名——避免再次出现
 *       「默认值被当成用户选择、刷新即丢」的问题。
 */
import { ref, computed, onMounted } from 'vue'
import { Brush, Check } from '@element-plus/icons-vue'
import {
  DEFAULT_UI_VARIANT,
  readStoredUiVariant,
  writeStoredUiVariant,
  applyUiVariant,
  type UiVariant,
} from '@/styles/uiVariant'

interface VariantOption {
  value: UiVariant
  label: string
  desc: string
  /** 预览色块填充色（纯预览用，允许硬编码） */
  swatch: string
  /** 预览色块描边色 */
  swatchBorder: string
}

const options: VariantOption[] = [
  { value: 'v1', label: '清透白', desc: '浅色侧栏 · 舒展留白', swatch: '#ffffff', swatchBorder: 'var(--app-border-base)' },
  { value: 'v2', label: '深空', desc: '深色侧栏 · 科技感', swatch: '#151922', swatchBorder: 'transparent' },
  { value: 'v3', label: '紧凑专业', desc: '高密度 · 一屏更多行', swatch: '#ffffff', swatchBorder: 'var(--app-border-base)' },
]

/** 当前变体：初始值取唯一真相源的默认值，挂载后再同步为已存储值 */
const current = ref<UiVariant>(DEFAULT_UI_VARIANT)

/** 当前选项的中文名，用于 tooltip；兜底项取自默认变体对应选项，避免张冠李戴 */
const currentLabel = computed<string>(
  () =>
    options.find((o) => o.value === current.value)?.label ??
    options.find((o) => o.value === DEFAULT_UI_VARIANT)!.label
)

/** 切换变体：仅用户显式选择时才落盘，并立即生效（不改结构，仅换令牌） */
function select(value: UiVariant): void {
  current.value = value
  writeStoredUiVariant(value)
  applyUiVariant(value)
}

onMounted(() => {
  // 只读不写：默认值不应被当作「用户选择」落盘，否则第二次刷新就会丢回默认
  current.value = readStoredUiVariant()
})
</script>

<style scoped>
/* ---------- 触发按钮：低调次要样式，不使用主色实底 ---------- */
.ui-variant-trigger {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  height: 30px;
  padding: 0 10px;
  font-size: var(--app-fs-sm);
  font-family: inherit;
  color: var(--app-text-regular);
  background-color: transparent;
  border: 1px solid var(--app-border-base);
  border-radius: var(--app-radius-md);
  cursor: pointer;
  transition: color 0.16s ease, border-color 0.16s ease, background-color 0.16s ease;
}

.ui-variant-trigger:hover {
  color: var(--app-accent);
  border-color: var(--app-accent);
  background-color: var(--app-accent-weak);
}

.ui-variant-trigger__icon {
  font-size: 15px;
}

.ui-variant-trigger__text {
  line-height: 1;
}

/* ---------- 弹层内容 ---------- */
.ui-variant-list {
  padding: 2px 0;
}

.ui-variant-list__title {
  padding: 2px 8px 8px;
  font-size: var(--app-fs-xs);
  color: var(--app-text-placeholder);
}

.ui-variant-option {
  display: flex;
  align-items: center;
  gap: var(--app-sp-3);
  padding: 8px 10px;
  border-radius: var(--app-radius-md);
  cursor: pointer;
  transition: background-color 0.16s ease;
}

.ui-variant-option:hover {
  background-color: var(--app-bg-hover);
}

.ui-variant-option.is-active {
  background-color: var(--app-accent-weak);
}

.ui-variant-option__swatch {
  flex: 0 0 auto;
  width: 14px;
  height: 14px;
  border-radius: var(--app-radius-sm);
  border: 1px solid var(--app-border-base);
}

.ui-variant-option__body {
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
  flex: 1 1 auto;
}

.ui-variant-option__name {
  font-size: var(--app-fs-base);
  font-weight: 500;
  color: var(--app-text-primary);
  line-height: 1.3;
}

.ui-variant-option__desc {
  font-size: var(--app-fs-xs);
  color: var(--app-text-secondary);
  line-height: 1.3;
}

.ui-variant-option__check {
  flex: 0 0 auto;
  font-size: 14px;
  color: var(--app-accent);
}
</style>
