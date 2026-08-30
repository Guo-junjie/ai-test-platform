<template>
  <div class="kb-qa">
    <!-- 顶栏 -->
    <el-card shadow="hover" class="qa-header">
      <div class="qa-header-inner">
        <div class="qa-title">
          <span class="qa-title-main">知识问答</span>
          <span class="qa-title-sub">基于知识库的 AI 助手，回答附来源引用</span>
        </div>
        <div class="qa-actions">
          <el-select
            v-model="projectFilter"
            placeholder="全部项目（不限）"
            clearable
            style="width: 200px"
          >
            <el-option v-for="p in projects" :key="p.id" :label="p.name" :value="p.id" />
          </el-select>
          <el-button @click="clearSession">清空会话</el-button>
        </div>
      </div>
    </el-card>

    <!-- 消息区 -->
    <el-card shadow="never" class="qa-body">
      <div ref="msgListRef" class="msg-list">
        <el-empty v-if="!messages.length" description="向知识库提问，例如：Trap 丢失该怎么测试？登录接口有什么规范要求？" />

        <div v-for="(msg, idx) in messages" :key="idx" :class="['msg-row', msg.role]">
          <div class="msg-avatar">{{ msg.role === 'user' ? '我' : 'AI' }}</div>
          <div class="msg-bubble">
            <!-- 用户消息 -->
            <template v-if="msg.role === 'user'">
              <div class="msg-text">{{ msg.content }}</div>
            </template>

            <!-- AI 消息 -->
            <template v-else>
              <div class="msg-text">
                <template v-for="(seg, si) in parseCitations(msg.content)" :key="si">
                  <span v-if="seg.type === 'text'">{{ seg.text }}</span>
                  <el-tooltip
                    v-else
                    :content="citationTooltip(msg, seg.num)"
                    placement="top"
                    :hide-after="0"
                  >
                    <sup class="cite-tag">[{{ seg.num }}]</sup>
                  </el-tooltip>
                </template>
              </div>

              <!-- 来源引用列表 -->
              <div v-if="msg.sources && msg.sources.length" class="msg-sources">
                <div class="sources-toggle" @click="toggleSources(idx)">
                  {{ msg.sourcesExpanded ? '收起来源' : `查看来源（${msg.sources.length}）` }}
                </div>
                <div v-if="msg.sourcesExpanded" class="sources-list">
                  <div v-for="s in msg.sources" :key="s.index" class="source-item">
                    <el-tag size="small" effect="plain">[{{ s.index }}]</el-tag>
                    <el-tag size="small" :type="kbTagType(s.kb_type)" effect="plain">
                      {{ kbLabel(s.kb_type) }}
                    </el-tag>
                    <span class="source-name">{{ s.source || s.source_ref }}</span>
                    <span class="source-score" v-if="s.score">score {{ s.score }}</span>
                    <div class="source-content">{{ s.content }}</div>
                  </div>
                </div>
              </div>

              <!-- 反馈按钮 -->
              <div v-if="!msg.loading" class="msg-feedback">
                <el-button
                  size="small"
                  text
                  :type="msg.feedback === 'up' ? 'primary' : ''"
                  @click="sendFeedback(msg, idx, 'up')"
                >👍 有帮助</el-button>
                <el-button
                  size="small"
                  text
                  :type="msg.feedback === 'down' ? 'danger' : ''"
                  @click="openFeedbackDialog(msg, idx)"
                >👎 没帮助</el-button>
                <span v-if="msg.feedbackSubmitted" class="feedback-done">已提交，感谢反馈</span>
              </div>
            </template>
          </div>
        </div>

        <div v-if="asking" class="msg-row assistant">
          <div class="msg-avatar">AI</div>
          <div class="msg-bubble">
            <el-icon class="is-loading"><Loading /></el-icon>
            正在检索知识库并生成回答…
          </div>
        </div>
      </div>

      <!-- 输入区 -->
      <div class="qa-input">
        <el-input
          v-model="input"
          type="textarea"
          :rows="2"
          resize="none"
          placeholder="输入问题，Enter 发送（Shift+Enter 换行）"
          :disabled="asking"
          @keydown.enter.exact.prevent="handleAsk"
        />
        <el-button
          type="primary"
          :loading="asking"
          :disabled="!input.trim()"
          @click="handleAsk"
        >
          发送
        </el-button>
      </div>
    </el-card>

    <!-- 点踩评论弹窗 -->
    <el-dialog v-model="feedbackDialogVisible" title="告诉我们哪里没帮助" width="480px">
      <el-input
        v-model="feedbackComment"
        type="textarea"
        :rows="3"
        placeholder="可选：例如答案与问题无关 / 引用来源不对 / 内容过时…"
      />
      <template #footer>
        <el-button @click="feedbackDialogVisible = false">跳过</el-button>
        <el-button type="primary" @click="confirmFeedbackDown">提交</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, nextTick, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { knowledgeApi, projectApi } from '@/api'

interface QaSource {
  index: number
  kb_type: string
  source_ref: string
  source: string
  score: number
  content: string
}

interface ChatMsg {
  role: 'user' | 'assistant'
  content: string
  sources?: QaSource[]
  sourcesExpanded?: boolean
  loading?: boolean
  feedback?: 'up' | 'down'
  feedbackSubmitted?: boolean
}

const projects = ref<Array<{ id: string; name: string }>>([])
const projectFilter = ref<string>('')
const messages = ref<ChatMsg[]>([])
const input = ref<string>('')
const asking = ref<boolean>(false)
const msgListRef = ref<HTMLElement | null>(null)

const feedbackDialogVisible = ref<boolean>(false)
const feedbackComment = ref<string>('')
let feedbackTarget: { msg: ChatMsg; idx: number } | null = null

const KB_LABELS: Record<string, string> = {
  document: '知识文档',
  defect: '缺陷',
  case: '用例',
  doc: '接口资产',
  term: '术语',
}

function kbLabel(t: string): string {
  return KB_LABELS[t] || t
}

function kbTagType(t: string): 'success' | 'warning' | 'danger' | 'info' | 'primary' {
  const map: Record<string, 'success' | 'warning' | 'danger' | 'info' | 'primary'> = {
    document: 'success',
    defect: 'danger',
    case: 'primary',
    doc: 'warning',
    term: 'info',
  }
  return map[t] || 'info'
}

/** 把回答里的 [n] 引用标记解析为可悬停的引用段 */
function parseCitations(text: string): Array<{ type: 'text' | 'cite'; text?: string; num?: number }> {
  const out: Array<{ type: 'text' | 'cite'; text?: string; num?: number }> = []
  const re = /\[(\d{1,2})\]/g
  let last = 0
  let m: RegExpExecArray | null
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) out.push({ type: 'text', text: text.slice(last, m.index) })
    out.push({ type: 'cite', num: parseInt(m[1], 10) })
    last = m.index + m[0].length
  }
  if (last < text.length) out.push({ type: 'text', text: text.slice(last) })
  return out
}

function citationTooltip(msg: ChatMsg, num?: number): string {
  if (num === undefined) return '无效引用'
  const s = msg.sources?.find((x) => x.index === num)
  if (!s) return '未找到对应来源'
  return `${s.source || s.source_ref}\n${s.content}`
}

function toggleSources(idx: number): void {
  const msg = messages.value[idx]
  if (msg) msg.sourcesExpanded = !msg.sourcesExpanded
}

function scrollToBottom(): void {
  void nextTick(() => {
    if (msgListRef.value) msgListRef.value.scrollTop = msgListRef.value.scrollHeight
  })
}

function clearSession(): void {
  messages.value = []
}

async function handleAsk(): Promise<void> {
  const q = input.value.trim()
  if (!q || asking.value) return
  input.value = ''
  messages.value.push({ role: 'user', content: q })
  scrollToBottom()

  asking.value = true
  try {
    const res: any = await knowledgeApi.ask({
      question: q,
      project_id: projectFilter.value || undefined,
    })
    const d = res?.data ?? {}
    messages.value.push({
      role: 'assistant',
      content: d.answer || '（空回答）',
      sources: d.sources || [],
      sourcesExpanded: false,
    })
    scrollToBottom()
  } catch {
    messages.value.push({
      role: 'assistant',
      content: '抱歉，本次回答失败，请稍后重试。',
      sources: [],
    })
  } finally {
    asking.value = false
    scrollToBottom()
  }
}

function sendFeedback(msg: ChatMsg, idx: number, rating: 'up' | 'down'): void {
  void submitFeedback(msg, idx, rating, '')
}

function openFeedbackDialog(msg: ChatMsg, idx: number): void {
  feedbackTarget = { msg, idx }
  feedbackComment.value = ''
  feedbackDialogVisible.value = true
}

async function confirmFeedbackDown(): Promise<void> {
  if (!feedbackTarget) return
  feedbackDialogVisible.value = false
  await submitFeedback(
    feedbackTarget.msg,
    feedbackTarget.idx,
    'down',
    feedbackComment.value.trim()
  )
}

async function submitFeedback(
  msg: ChatMsg,
  idx: number,
  rating: 'up' | 'down',
  comment: string
): Promise<void> {
  if (msg.feedbackSubmitted) return
  // 找到对应的用户问题（往上最近一条 user 消息）
  let question = ''
  for (let i = idx - 1; i >= 0; i--) {
    if (messages.value[i].role === 'user') {
      question = messages.value[i].content
      break
    }
  }
  try {
    const res: any = await knowledgeApi.submitFeedback({
      question,
      answer: msg.content,
      rating,
      comment: comment || undefined,
      retrieved: (msg.sources || []).map((s) => ({
        index: s.index,
        kb_type: s.kb_type,
        source_ref: s.source_ref,
        source: s.source,
        score: s.score,
      })),
    })
    if (res?.code === 0) {
      msg.feedback = rating
      msg.feedbackSubmitted = true
    } else {
      ElMessage.warning(res?.message || '反馈提交失败')
    }
  } catch {
    /* 拦截器已处理 */
  }
}

onMounted(async () => {
  try {
    const res: any = await projectApi.getList()
    projects.value = res?.data ?? []
  } catch {
    projects.value = []
  }
})
</script>

<style scoped>
.kb-qa {
  display: flex;
  flex-direction: column;
  gap: 12px;
  height: calc(100vh - 130px);
}
.qa-header-inner {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.qa-title-main {
  font-size: 16px;
  font-weight: 600;
  margin-right: 10px;
}
.qa-title-sub {
  font-size: 12px;
  color: #909399;
}
.qa-actions {
  display: flex;
  gap: 8px;
}
.qa-body {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.qa-body :deep(.el-card__body) {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  padding-bottom: 12px;
}
.msg-list {
  flex: 1;
  overflow-y: auto;
  padding: 4px 8px;
}
.msg-row {
  display: flex;
  gap: 10px;
  margin-bottom: 16px;
}
.msg-row.user {
  flex-direction: row-reverse;
}
.msg-avatar {
  flex-shrink: 0;
  width: 34px;
  height: 34px;
  border-radius: 50%;
  background: #409eff;
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
}
.msg-row.user .msg-avatar {
  background: #67c23a;
}
.msg-bubble {
  max-width: 78%;
  background: #f5f7fa;
  border-radius: 8px;
  padding: 10px 14px;
}
.msg-row.user .msg-bubble {
  background: #ecf5ff;
}
.msg-text {
  font-size: 14px;
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
}
.cite-tag {
  color: #409eff;
  cursor: default;
  font-weight: 600;
  margin: 0 1px;
}
.msg-sources {
  margin-top: 8px;
  border-top: 1px dashed #dcdfe6;
  padding-top: 6px;
}
.sources-toggle {
  font-size: 12px;
  color: #409eff;
  cursor: pointer;
}
.sources-list {
  margin-top: 6px;
}
.source-item {
  background: #fff;
  border: 1px solid #ebeef5;
  border-radius: 6px;
  padding: 6px 10px;
  margin-bottom: 6px;
  font-size: 12px;
}
.source-name {
  margin-left: 6px;
  color: #303133;
  font-weight: 500;
}
.source-score {
  float: right;
  color: #c0c4cc;
}
.source-content {
  margin-top: 4px;
  color: #606266;
  white-space: pre-wrap;
  word-break: break-word;
}
.msg-feedback {
  margin-top: 8px;
  display: flex;
  align-items: center;
  gap: 4px;
}
.feedback-done {
  font-size: 12px;
  color: #67c23a;
  margin-left: 8px;
}
.qa-input {
  display: flex;
  gap: 8px;
  align-items: flex-end;
  padding-top: 10px;
  border-top: 1px solid #ebeef5;
}
.qa-input .el-button {
  height: 54px;
}
</style>
