<template>
  <div class="case-generation">
    <el-card class="source-switcher" shadow="never">
      <div class="heading">
        <div>
          <h2>智能用例生成</h2>
          <p>选择输入来源，解析后生成可追溯的测试用例草稿，并统一进入用例库评审。</p>
        </div>
        <el-button type="primary" plain @click="goCaseLibrary">进入用例管理与评审</el-button>
      </div>

      <el-tabs v-model="activeSource" class="source-tabs">
        <el-tab-pane name="requirement">
          <template #label>
            <span class="tab-label">
              <el-icon><Document /></el-icon>
              <span>需求文档生成</span>
            </span>
          </template>
        </el-tab-pane>
        <el-tab-pane name="interface">
          <template #label>
            <span class="tab-label">
              <el-icon><Connection /></el-icon>
              <span>接口文档生成</span>
            </span>
          </template>
        </el-tab-pane>
      </el-tabs>

      <div class="source-description">
        <template v-if="activeSource === 'requirement'">
          从 PRD、需求说明或验收标准中提取功能点，生成可追溯的手工测试用例草稿。
        </template>
        <template v-else>
          从 OpenAPI、Swagger 或 HAR 中解析接口定义，导入接口资产并生成可执行的 API 测试用例草稿。
        </template>
      </div>
    </el-card>

    <keep-alive>
      <component :is="activeComponent" />
    </keep-alive>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Connection, Document } from '@element-plus/icons-vue'
import RequirementParse from '@/views/RequirementParse.vue'
import DocParser from '@/views/DocParser.vue'

type GenerationSource = 'requirement' | 'interface'

const route = useRoute()
const router = useRouter()

const activeSource = computed<GenerationSource>({
  get: () => (route.query.source === 'interface' ? 'interface' : 'requirement'),
  set: (source) => switchSource(source),
})
const activeComponent = computed(() =>
  activeSource.value === 'interface' ? DocParser : RequirementParse,
)

function switchSource(source: GenerationSource): void {
  const nextSource: GenerationSource = source === 'interface' ? 'interface' : 'requirement'
  if (nextSource === activeSource.value) return
  router.replace({
    path: '/case-generation',
    query: { ...route.query, source: nextSource },
  })
}

function goCaseLibrary(): void {
  router.push({
    path: '/case-library',
    query: route.query.project_id ? { project_id: route.query.project_id } : {},
  })
}
</script>

<style scoped>
.case-generation {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.source-switcher {
  border-color: var(--el-border-color-light);
}
.heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 20px;
}
.heading h2 {
  margin: 0;
  color: var(--el-text-color-primary);
  font-size: 20px;
}
.heading p {
  margin: 8px 0 0;
  color: var(--el-text-color-secondary);
  font-size: 13px;
  line-height: 1.6;
}
.source-tabs {
  margin-top: 14px;
}
.source-tabs :deep(.el-tabs__header) {
  margin-bottom: 8px;
}
.source-tabs :deep(.el-tabs__content) {
  display: none;
}
.tab-label {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 0 8px;
  font-weight: 600;
}
.source-description {
  color: var(--el-text-color-secondary);
  font-size: 13px;
  line-height: 1.7;
}
@media (max-width: 768px) {
  .heading {
    flex-direction: column;
  }
}
</style>
