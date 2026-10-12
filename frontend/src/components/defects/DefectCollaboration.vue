<template>
  <div class="collaboration" v-loading="loading">
    <div class="collaboration-toolbar">
      <div><b>协作动态</b><p>评论支持精确 @ 项目成员；关注后可接收后续变更通知。</p></div>
      <el-button :type="myWatcher ? 'default' : 'primary'" plain @click="toggleWatch">{{ myWatcher ? '取消关注' : '关注缺陷' }}</el-button>
    </div>
    <div class="watchers"><span>关注与抄送</span><el-tag v-for="item in watchers" :key="item.id" size="small" :type="item.kind === 'cc' ? 'warning' : 'info'">{{ item.username }}{{ item.kind === 'cc' ? ' · 抄送' : '' }}</el-tag><span v-if="!watchers.length" class="muted">暂无</span></div>

    <section class="comment-editor">
      <el-input v-model="body" type="textarea" :rows="4" maxlength="20000" show-word-limit placeholder="补充复现信息、处理进度或验证结论" aria-label="缺陷评论内容" />
      <div class="editor-actions">
        <el-select v-model="mentionIds" multiple filterable collapse-tags placeholder="@ 提醒项目成员" aria-label="选择提醒成员"><el-option v-for="item in participants" :key="item.id" :label="`@${item.username}`" :value="item.id" /></el-select>
        <el-button type="primary" :loading="submitting" :disabled="!body.trim()" @click="submitComment">发布评论</el-button>
      </div>
    </section>

    <el-empty v-if="!comments.length && !loading" description="还没有评论，发布第一条协作记录" :image-size="70" />
    <div v-for="item in comments" :key="item.id" class="comment-item">
      <div class="comment-head"><div><b>{{ item.author_name }}</b><span>{{ defectTime(item.created_at) }}</span><el-tag v-if="item.edited_at" size="small" type="info">已编辑</el-tag></div><el-dropdown v-if="!item.deleted_at && (item.author_id === auth.user?.id || defect.permissions?.delete)" @command="(cmd: string) => commentCommand(cmd, item)"><el-button link :icon="MoreFilled" :aria-label="`${item.author_name} 评论操作`"/><template #dropdown><el-dropdown-menu><el-dropdown-item v-if="item.author_id === auth.user?.id" command="edit">编辑</el-dropdown-item><el-dropdown-item command="delete">删除</el-dropdown-item></el-dropdown-menu></template></el-dropdown></div>
      <p v-if="item.deleted_at" class="muted">该评论已删除</p><p v-else class="comment-body">{{ item.body }}</p>
      <div v-if="item.mention_user_ids?.length" class="mentions"><el-tag v-for="id in item.mention_user_ids" :key="id" size="small">@{{ participantName(id) }}</el-tag></div>
    </div>

    <el-divider />
    <div class="attachment-head"><div><b>附件</b><p>支持图片、PDF、文本、日志和 Office 文档；单个不超过 20MB。</p></div><label class="file-button"><input type="file" :disabled="uploading" @change="upload"/><span>{{ uploading ? '上传中…' : '上传附件' }}</span></label></div>
    <el-table :data="attachments" size="small" empty-text="暂无附件">
      <el-table-column prop="filename" label="文件名" min-width="240" show-overflow-tooltip />
      <el-table-column label="大小" width="100"><template #default="{ row }">{{ fileSize(row.size) }}</template></el-table-column>
      <el-table-column label="上传时间" width="170"><template #default="{ row }">{{ defectTime(row.created_at) }}</template></el-table-column>
      <el-table-column label="操作" width="150"><template #default="{ row }"><el-button link type="primary" @click="download(row)">下载</el-button><el-button link type="danger" @click="removeAttachment(row)">删除</el-button></template></el-table-column>
    </el-table>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { MoreFilled } from '@element-plus/icons-vue'
import { defectsApi } from '@/api'
import { useAuthStore } from '@/stores'
import { defectTime } from '@/types/defects'

const props = defineProps<{ defect: any; active: boolean }>()
const emit = defineEmits<{ changed: [] }>()
const auth = useAuthStore()
const loading = ref(false), submitting = ref(false), uploading = ref(false)
const comments = ref<any[]>([]), watchers = ref<any[]>([]), attachments = ref<any[]>([]), participants = ref<any[]>([])
const body = ref(''), mentionIds = ref<string[]>([])
const myWatcher = computed(() => watchers.value.find(item => item.user_id === auth.user?.id && item.kind === 'watch'))
let loadedId = ''

async function load() {
  if (!props.defect?.id) return
  loading.value = true
  try {
    const [commentRes, watcherRes, attachmentRes, peopleRes]: any = await Promise.all([
      defectsApi.comments(props.defect.id), defectsApi.watchers(props.defect.id), defectsApi.attachments(props.defect.id),
      defectsApi.participants(props.defect.project_id),
    ])
    comments.value = commentRes.data.items; watchers.value = watcherRes.data.items; attachments.value = attachmentRes.data.items; participants.value = peopleRes.data.items
    loadedId = props.defect.id
  } finally { loading.value = false }
}
watch(() => [props.active, props.defect?.id], () => { if (props.active && loadedId !== props.defect?.id) void load() }, { immediate: true })
async function submitComment() { submitting.value = true; try { await defectsApi.addComment(props.defect.id, { body: body.value, mention_user_ids: mentionIds.value, attachment_ids: [] }); body.value = ''; mentionIds.value = []; await load(); emit('changed'); ElMessage.success('评论已发布') } finally { submitting.value = false } }
async function toggleWatch() { if (myWatcher.value) await defectsApi.removeWatcher(props.defect.id, myWatcher.value.id); else await defectsApi.addWatcher(props.defect.id); await load(); ElMessage.success(myWatcher.value ? '已关注' : '已取消关注') }
async function commentCommand(command: string, item: any) { if (command === 'delete') { await ElMessageBox.confirm('删除后保留审计痕迹，确定继续？', '删除评论', { type: 'warning' }); await defectsApi.removeComment(props.defect.id, item.id) } else { const result: any = await ElMessageBox.prompt('修改评论内容', '编辑评论', { inputValue: item.body, inputType: 'textarea', inputValidator: (value: string) => !!value.trim() || '评论不能为空' }); await defectsApi.updateComment(props.defect.id, item.id, { body: result.value, mention_user_ids: item.mention_user_ids || [], expected_version: item.row_version }) } await load(); emit('changed') }
async function upload(event: Event) { const input = event.target as HTMLInputElement; const file = input.files?.[0]; if (!file) return; uploading.value = true; try { await defectsApi.uploadAttachment(props.defect.project_id, file, props.defect.id); await load(); emit('changed'); ElMessage.success('附件已上传') } finally { uploading.value = false; input.value = '' } }
async function download(row: any) { const blob: any = await defectsApi.downloadAttachment(row.id); const url = URL.createObjectURL(blob); const anchor = document.createElement('a'); anchor.href = url; anchor.download = row.filename; anchor.click(); URL.revokeObjectURL(url) }
async function removeAttachment(row: any) { await ElMessageBox.confirm(`确定删除附件「${row.filename}」？`, '删除附件', { type: 'warning' }); await defectsApi.removeAttachment(row.id); await load(); emit('changed') }
function participantName(id: string) { return participants.value.find(item => item.id === id)?.username || '项目成员' }
function fileSize(size: number) { return size < 1024 * 1024 ? `${Math.ceil(size / 1024)} KB` : `${(size / 1024 / 1024).toFixed(1)} MB` }
</script>

<style scoped>
.collaboration{display:grid;gap:16px;padding:4px}.collaboration-toolbar,.attachment-head,.comment-head,.editor-actions{display:flex;justify-content:space-between;align-items:center;gap:14px}.collaboration-toolbar p,.attachment-head p{margin:5px 0 0;color:var(--el-text-color-secondary);font-size:12px}.watchers,.mentions{display:flex;align-items:center;gap:7px;flex-wrap:wrap}.watchers>span:first-child{font-size:13px;color:var(--el-text-color-secondary);margin-right:4px}.comment-editor{padding:14px;border:1px solid var(--el-border-color);border-radius:10px;background:var(--el-fill-color-lighter)}.editor-actions{margin-top:10px}.editor-actions .el-select{max-width:420px}.comment-item{padding:14px 2px;border-bottom:1px solid var(--el-border-color-lighter)}.comment-head>div{display:flex;gap:9px;align-items:center}.comment-head span{font-size:12px;color:var(--el-text-color-secondary)}.comment-body{white-space:pre-wrap;line-height:1.75;margin:10px 0}.muted{color:var(--el-text-color-secondary)}.file-button{display:inline-flex;height:30px;align-items:center;padding:0 14px;border-radius:4px;border:1px solid var(--el-color-primary);color:var(--el-color-primary);cursor:pointer;font-size:13px}.file-button input{display:none}@media(max-width:620px){.collaboration-toolbar,.attachment-head,.editor-actions{align-items:flex-start;flex-direction:column}.editor-actions .el-select{width:100%;max-width:none}}
</style>
