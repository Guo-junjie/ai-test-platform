<template>
  <div class="ws-plans">
    <el-card shadow="hover">
      <template #header>
        <div class="card-row">
          <span>测试计划（发布后的计划可执行；修改后需重新发布）</span>
          <el-button size="small" @click="loadPlans" :loading="loading">刷新</el-button>
        </div>
      </template>

      <el-table :data="plans" v-loading="loading" stripe>
        <el-table-column prop="name" label="计划名称" min-width="180" show-overflow-tooltip />
        <el-table-column label="用例" width="110" align="center">
          <template #default="{ row }">{{ row.stats?.enabled_cases ?? 0 }} / {{ row.stats?.total_cases ?? 0 }}</template>
        </el-table-column>
        <el-table-column label="发布状态" width="200" align="center">
          <template #default="{ row }">
            <template v-if="row.published_revision">
              <el-tag size="small" type="primary">r{{ row.published_revision }}</el-tag>
              <el-tag v-if="row.has_unpublished_changes" size="small" type="warning" style="margin-left: 4px">
                有未发布修改
              </el-tag>
            </template>
            <el-tag v-else size="small" type="danger">未发布</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="220" fixed="right">
          <template #default="{ row }">
            <el-button
              size="small"
              type="primary"
              plain
              :disabled="!row.published_revision"
              @click="openExecute(row)"
            >
              执行
            </el-button>
            <el-button
              size="small"
              type="success"
              plain
              :disabled="row.published_revision && !row.has_unpublished_changes"
              :loading="row._publishing"
              @click="publish(row)"
            >
              {{ row.published_revision ? '重新发布' : '发布' }}
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <el-empty v-if="!loading && plans.length === 0"
        description="还没有测试计划 —— 用例库中选勾用例后「加入计划」创建" :image-size="70" />
    </el-card>

    <!-- 执行对话框：选择已发布环境 -->
    <el-dialog v-model="execVisible" :title="`执行计划 - ${execPlan?.name || ''}`" width="520px"
      :close-on-click-modal="false">
      <el-form label-width="100px">
        <el-form-item label="执行环境" required>
          <el-select v-model="execEnvId" placeholder="选择已发布环境" :loading="envsLoading" style="width: 100%">
            <el-option v-for="e in envs" :key="e.id" :label="`${e.name}（${e.base_url}）`" :value="e.id" />
          </el-select>
          <div class="form-tip">
            按已发布修订版 r{{ execPlan?.published_revision }} 执行；环境来自项目环境档案（发布时的配置快照）
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="execVisible = false">取消</el-button>
        <el-button type="primary" :loading="executing" :disabled="!execEnvId" @click="submitExecute">
          启动执行
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script lang="ts">
/** 工作区·测试计划（M4）—— 发布状态一眼可见，执行不出工作区。 */
import { defineComponent } from 'vue'
import { ElMessage } from 'element-plus'
import { environmentApi, planApi } from '@/api'

export default defineComponent({
  name: 'ProjectPlans',
  data() {
    return {
      projectId: (this.$route.params.id as string) || '',
      plans: [] as any[],
      loading: false,
      execVisible: false,
      executing: false,
      execPlan: null as any,
      execEnvId: '',
      envs: [] as any[],
      envsLoading: false,
    }
  },
  methods: {
    async loadPlans(): Promise<void> {
      this.loading = true
      try {
        const res: any = await planApi.list({ project_id: this.projectId, page: 1, page_size: 100 })
        this.plans = res?.data?.list || []
      } catch {
        this.plans = []
      } finally {
        this.loading = false
      }
    },
    async loadEnvs(): Promise<void> {
      this.envsLoading = true
      try {
        const res: any = await environmentApi.list(this.projectId)
        this.envs = (res?.data?.list || []).filter((e: any) => e.status === 'published')
        if (this.envs.length > 0 && !this.execEnvId) {
          this.execEnvId = this.envs[0].id
        }
      } catch {
        this.envs = []
      } finally {
        this.envsLoading = false
      }
    },
    openExecute(row: any): void {
      this.execPlan = row
      this.execEnvId = ''
      this.execVisible = true
      this.loadEnvs()
    },
    async submitExecute(): Promise<void> {
      if (!this.execPlan || !this.execEnvId) return
      this.executing = true
      try {
        const res: any = await planApi.execute(this.execPlan.id, {
          environment_profile_id: this.execEnvId,
        })
        ElMessage.success('计划已启动 —— 到「运行中心」查看时间线与结果')
        this.execVisible = false
        this.$router.push(`/projects/${this.projectId}/runs`)
        void res
      } catch {
        /* 拦截器已提示 */
      } finally {
        this.executing = false
      }
    },
    async publish(row: any): Promise<void> {
      row._publishing = true
      try {
        const res: any = await planApi.publish(row.id)
        const d = res?.data || {}
        if (d.unchanged) {
          ElMessage.info('当前状态与最新已发布修订版一致')
        } else {
          ElMessage.success(`已发布修订版 r${d.revision}（${d.enabled_count} 条启用用例）`)
        }
        this.loadPlans()
      } catch {
        /* 拦截器已提示 */
      } finally {
        row._publishing = false
      }
    },
  },
  mounted() {
    this.loadPlans()
  },
})
</script>

<style scoped>
.card-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.form-tip {
  font-size: 12px;
  color: #909399;
  line-height: 1.6;
  margin-top: 4px;
}
</style>
