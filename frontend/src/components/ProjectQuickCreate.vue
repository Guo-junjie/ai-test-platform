<template>
  <el-dialog
    :model-value="visible"
    title="新建项目"
    width="480px"
    :close-on-click-modal="false"
    @update:model-value="$emit('update:visible', $event)"
  >
    <el-form label-width="70px">
      <el-form-item label="名称" required>
        <el-input v-model="name" placeholder="例如：订单中心" maxlength="200" show-word-limit />
      </el-form-item>
      <el-form-item label="描述">
        <el-input v-model="description" type="textarea" :rows="2" placeholder="项目说明（可选）" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="$emit('update:visible', false)">取消</el-button>
      <el-button type="primary" :loading="creating" @click="submit">创建</el-button>
    </template>
  </el-dialog>
</template>

<script lang="ts">
/**
 * ProjectQuickCreate —— 项目快捷新建弹窗（共享组件）
 *
 * 场景：测试任务 / 用例库等页面的「项目」下拉旁点「+ 新建」，
 * 创建成功后 emit('created', project)，父组件负责刷新下拉并选中。
 * 仓库配置等完整信息请到「项目管理」页维护。
 */
import { defineComponent } from 'vue'
import { ElMessage } from 'element-plus'
import { projectApi } from '@/api'

export default defineComponent({
  name: 'ProjectQuickCreate',
  props: {
    visible: { type: Boolean, default: false },
  },
  emits: ['update:visible', 'created'],
  data() {
    return {
      creating: false,
      name: '',
      description: '',
    }
  },
  watch: {
    visible(open: boolean): void {
      if (open) {
        this.name = ''
        this.description = ''
      }
    },
  },
  methods: {
    async submit(): Promise<void> {
      const name = this.name.trim()
      if (!name) {
        ElMessage.warning('请输入项目名称')
        return
      }
      this.creating = true
      try {
        const res: any = await projectApi.create({
          name,
          description: this.description.trim() || undefined,
        })
        ElMessage.success(`项目「${name}」创建成功`)
        this.$emit('update:visible', false)
        this.$emit('created', res?.data || { id: '', name })
      } catch {
        /* 拦截器已提示（重名/无权限） */
      } finally {
        this.creating = false
      }
    },
  },
})
</script>
