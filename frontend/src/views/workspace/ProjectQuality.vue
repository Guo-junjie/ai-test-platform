<template>
  <div class="ws-quality">
    <el-card shadow="hover">
      <template #header>质量结果 —— 报告、缺陷、覆盖率与趋势（均按本项目过滤或可过滤）</template>
      <el-row :gutter="16">
        <el-col :xs="24" :md="12" v-for="c in cards" :key="c.title">
          <div class="q-card" @click="$router.push(c.to)">
            <div class="q-title">{{ c.title }}</div>
            <div class="q-desc">{{ c.desc }}</div>
            <div class="q-link">{{ c.link }} →</div>
          </div>
        </el-col>
      </el-row>
      <el-alert type="info" :closable="false" show-icon style="margin-top: 12px"
        title="报告 → 关联数据 可直达本任务的缺陷列表与覆盖率；运行详情的时间线提供完整执行过程证据" />
    </el-card>
  </div>
</template>

<script lang="ts">
/** 工作区·质量结果（M4）—— 质量产出物入口卡片。 */
import { defineComponent } from 'vue'

export default defineComponent({
  name: 'ProjectQuality',
  data() {
    return {
      projectId: (this.$route.params.id as string) || '',
      cards: [
        { title: '测试报告', desc: 'HTML/PDF 报告、AI 分析、分享', link: '测试报告', to: '/report' },
        { title: '缺陷中心', desc: '本项目全部缺陷的登记与跟踪', link: '缺陷中心', to: `/defects?project_id=${(this.$route.params.id as string) || ''}` },
        { title: '代码覆盖率', desc: 'Cobertura/Jaoco 等覆盖率报告与文件级明细', link: '代码覆盖率', to: `/coverage?project_id=${(this.$route.params.id as string) || ''}` },
        { title: '质量趋势', desc: '通过率、评分、缺陷的趋势变化', link: '质量趋势', to: '/quality-trend' },
      ],
    }
  },
})
</script>

<style scoped>
.q-card {
  border: 1px solid #ebeef5;
  border-radius: 6px;
  padding: 16px;
  margin-bottom: 16px;
  cursor: pointer;
  transition: all 0.2s;
}
.q-card:hover {
  border-color: #409eff;
  box-shadow: 0 2px 8px rgba(64, 158, 255, 0.1);
}
.q-title {
  font-weight: 600;
  color: #303133;
}
.q-desc {
  font-size: 12px;
  color: #909399;
  margin: 6px 0;
}
.q-link {
  font-size: 12px;
  color: #409eff;
}
</style>
