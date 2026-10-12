<template>
  <el-dialog
    v-model="visible"
    title="批量导入用例"
    width="min(960px, 96vw)"
    destroy-on-close
    :close-on-click-modal="!busy"
    @open="reset"
  >
    <div class="import-toolbar">
      <div>
        <strong>统一导入手工用例与 API 用例</strong>
        <p>先下载模板填写。上传后平台会校验完整字段、请求与断言，并识别项目内同名用例。</p>
      </div>
      <el-button :icon="Download" :loading="downloading" @click="downloadTemplate">下载导入模板</el-button>
    </div>

    <el-upload
      v-if="!previewRows.length"
      drag
      :auto-upload="false"
      :show-file-list="false"
      accept=".csv,.json,.xlsx,.xlsm"
      :disabled="busy || !projectId"
      :on-change="previewFile"
      class="import-upload"
    >
      <el-icon class="upload-icon"><UploadFilled /></el-icon>
      <div class="el-upload__text">拖拽文件到此处，或<em>点击选择文件</em></div>
      <template #tip><div class="el-upload__tip">支持 CSV、JSON、XLSX、XLSM，单次最多 2000 条。</div></template>
    </el-upload>

    <template v-else>
      <div class="preview-summary">
        <el-alert
          :type="failedCount ? 'warning' : 'success'"
          :closable="false"
          show-icon
          :title="`共 ${previewRows.length} 条：校验通过 ${successCount} 条，错误 ${failedCount} 条，同名 ${duplicateCount} 条。`"
        />
        <el-button :disabled="busy" @click="clearPreview">重新选择文件</el-button>
      </div>

      <div class="duplicate-policy">
        <span>同名处理</span>
        <el-radio-group v-model="duplicateStrategy" :disabled="!duplicateCount">
          <el-radio-button value="skip">跳过同名用例</el-radio-button>
          <el-radio-button value="create">仍创建为新草稿</el-radio-button>
        </el-radio-group>
        <small>同名判断范围为当前项目，比较时忽略标题首尾空格和大小写。</small>
      </div>

      <el-table :data="previewRows" max-height="430" border>
        <el-table-column prop="row_no" label="行" width="64" />
        <el-table-column label="用例名称" min-width="220">
          <template #default="{ row }">
            <span>{{ row.data?.title || '—' }}</span>
            <el-tag v-if="row.duplicate" size="small" type="warning" class="duplicate-tag">同名</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="执行类型" width="110">
          <template #default="{ row }">{{ row.data?.execution_kind === 'manual' ? '手工用例' : 'API 用例' }}</template>
        </el-table-column>
        <el-table-column label="目录" min-width="120">
          <template #default="{ row }">{{ row.data?.folder || '未归类' }}</template>
        </el-table-column>
        <el-table-column label="校验结果" min-width="300">
          <template #default="{ row }">
            <el-tag size="small" :type="row.valid ? 'success' : 'danger'">{{ row.valid ? '通过' : '错误' }}</el-tag>
            <span v-if="row.errors?.length" class="row-error">{{ row.errors.join('；') }}</span>
            <span v-else-if="row.duplicate" class="row-warning">{{ duplicateStrategy === 'skip' ? '导入时将跳过' : '将创建独立草稿' }}</span>
          </template>
        </el-table-column>
      </el-table>
    </template>

    <template #footer>
      <div class="dialog-footer">
        <span v-if="previewRows.length" class="commit-hint">本次将导入 {{ importableCount }} 条草稿</span>
        <el-button :disabled="busy" @click="visible = false">取消</el-button>
        <el-button
          v-if="previewRows.length"
          type="primary"
          :loading="committing"
          :disabled="!importableCount"
          @click="commitImport"
        >确认导入</el-button>
      </div>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { Download, UploadFilled } from '@element-plus/icons-vue'
import { ElMessage, type UploadFile } from 'element-plus'
import { caseApi } from '@/api'

const props = defineProps<{ modelValue: boolean; projectId: string }>()
const emit = defineEmits<{
  (event: 'update:modelValue', value: boolean): void
  (event: 'imported', result: { imported: number; skipped: number; asset_ids: string[] }): void
}>()

const visible = computed({ get: () => props.modelValue, set: value => emit('update:modelValue', value) })
const previewRows = ref<any[]>([])
const successCount = ref(0)
const failedCount = ref(0)
const duplicateCount = ref(0)
const duplicateStrategy = ref<'skip' | 'create'>('skip')
const previewing = ref(false)
const committing = ref(false)
const downloading = ref(false)
const busy = computed(() => previewing.value || committing.value || downloading.value)
const validRows = computed(() => previewRows.value.filter(row => row.valid))
const importableCount = computed(() => validRows.value.filter(row => duplicateStrategy.value === 'create' || !row.duplicate).length)

function reset() {
  previewRows.value = []
  successCount.value = 0
  failedCount.value = 0
  duplicateCount.value = 0
  duplicateStrategy.value = 'skip'
}
function clearPreview() { reset() }

async function previewFile(uploadFile: UploadFile) {
  if (!props.projectId || !uploadFile.raw) return
  previewing.value = true
  try {
    const response: any = await caseApi.importPreview(props.projectId, uploadFile.raw)
    const data = response?.data || {}
    previewRows.value = data.rows || []
    successCount.value = data.success_count || 0
    failedCount.value = data.failed_count || 0
    duplicateCount.value = data.duplicate_count || 0
    if (!previewRows.value.length) ElMessage.warning('文件中没有可识别的数据行')
  } finally { previewing.value = false }
}

async function downloadTemplate() {
  downloading.value = true
  try {
    const response: any = await caseApi.importTemplate()
    const blob = response instanceof Blob ? response : new Blob([response], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = '用例批量导入模板.xlsx'
    link.click()
    URL.revokeObjectURL(url)
  } finally { downloading.value = false }
}

async function commitImport() {
  committing.value = true
  try {
    const response: any = await caseApi.importCommit({
      project_id: props.projectId,
      duplicate_strategy: duplicateStrategy.value,
      rows: validRows.value.map(row => row.data),
    })
    const result = response?.data || { imported: 0, skipped: 0, asset_ids: [] }
    const skippedText = result.skipped ? `，跳过 ${result.skipped} 条同名用例` : ''
    ElMessage.success(`已导入 ${result.imported} 条用例草稿${skippedText}`)
    emit('imported', result)
    visible.value = false
  } finally { committing.value = false }
}
</script>

<style scoped>
.import-toolbar, .preview-summary, .duplicate-policy, .dialog-footer { display: flex; align-items: center; gap: 12px; }
.import-toolbar { justify-content: space-between; margin-bottom: 18px; }
.import-toolbar p { margin: 5px 0 0; color: var(--el-text-color-secondary); font-size: 13px; }
.import-upload { margin: 8px 0 4px; }
.upload-icon { color: var(--el-color-primary); font-size: 42px; }
.preview-summary { margin-bottom: 14px; }
.preview-summary .el-alert { flex: 1; }
.duplicate-policy { margin-bottom: 14px; padding: 12px; background: var(--el-fill-color-lighter); border-radius: 8px; }
.duplicate-policy > span { font-weight: 600; }
.duplicate-policy small { color: var(--el-text-color-secondary); }
.duplicate-tag { margin-left: 8px; }
.row-error { margin-left: 8px; color: var(--el-color-danger); }
.row-warning { margin-left: 8px; color: var(--el-color-warning); }
.dialog-footer { justify-content: flex-end; }
.commit-hint { margin-right: auto; color: var(--el-text-color-secondary); font-size: 13px; }
@media (max-width: 680px) {
  .import-toolbar, .preview-summary, .duplicate-policy { align-items: stretch; flex-direction: column; }
}
</style>
