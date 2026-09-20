<template>
  <div class="qa-workspace">
    <aside class="session-panel">
      <div class="session-panel-header">
        <div><div class="panel-title">知识问答</div><div class="panel-subtitle">历史会话自动保存</div></div>
        <el-button type="primary" :icon="Plus" circle title="新建会话" @click="startNewSession" />
      </div>
      <el-input v-model="sessionKeyword" :prefix-icon="Search" clearable placeholder="搜索历史会话"
        @keyup.enter="loadConversations" @clear="loadConversations" />
      <div class="session-list" v-loading="sessionLoading">
        <el-empty v-if="!sessionLoading && !conversations.length" :image-size="70" description="暂无历史会话" />
        <div v-for="conversation in conversations" :key="conversation.id"
          :class="['session-item', { active: conversation.id === activeConversationId }]"
          @click="selectConversation(conversation.id)">
          <div class="session-main">
            <div class="session-title">{{ conversation.title }}</div>
            <div class="session-meta"><span>{{ conversation.project_name || '全部项目' }}</span><span>{{ relativeTime(conversation.last_message_at) }}</span></div>
          </div>
          <div class="session-actions" @click.stop>
            <el-button text :icon="EditPen" title="重命名" @click="renameConversation(conversation)" />
            <el-button text type="danger" :icon="Delete" title="删除" @click="removeConversation(conversation)" />
          </div>
        </div>
      </div>
    </aside>

    <main class="chat-panel">
      <header class="chat-header">
        <div><div class="chat-title">{{ activeConversation?.title || '新对话' }}</div><div class="chat-subtitle">基于企业知识库回答，并保留引用来源</div></div>
        <div class="chat-actions">
          <el-select v-model="projectFilter" placeholder="全部项目知识" clearable
            :disabled="messages.length > 0 || asking" style="width: 210px">
            <el-option v-for="project in projects" :key="project.id" :label="project.name" :value="project.id" />
          </el-select>
          <el-button plain @click="$router.push('/knowledge')">管理知识库</el-button>
        </div>
      </header>

      <div ref="msgListRef" class="msg-list">
        <div v-if="messageLoading" class="center-state"><el-icon class="is-loading"><Loading /></el-icon><span>正在读取会话…</span></div>
        <div v-else-if="!messages.length" class="welcome-state">
          <div class="welcome-icon">AI</div><h2>想了解哪些测试知识？</h2>
          <p>可以查询测试规范、历史缺陷、接口资产、测试用例和业务术语。</p>
          <div class="suggestions"><button v-for="item in suggestions" :key="item" type="button" @click="useSuggestion(item)">{{ item }}</button></div>
        </div>
        <template v-else>
          <div v-for="(msg, idx) in messages" :key="msg.id || idx" :class="['msg-row', msg.role]">
            <div class="msg-avatar">{{ msg.role === 'user' ? '我' : 'AI' }}</div>
            <div class="msg-bubble">
              <div v-if="msg.role === 'user'" class="msg-text">{{ msg.content }}</div>
              <template v-else>
                <div class="msg-text">
                  <template v-for="(segment, segmentIndex) in parseCitations(msg.content)" :key="segmentIndex">
                    <span v-if="segment.type === 'text'">{{ segment.text }}</span>
                    <el-tooltip v-else :content="citationTooltip(msg, segment.num)" placement="top" :hide-after="0">
                      <sup class="cite-tag">[{{ segment.num }}]</sup>
                    </el-tooltip>
                  </template>
                </div>
                <div v-if="msg.sources?.length" class="msg-sources">
                  <button class="sources-toggle" type="button" @click="msg.sourcesExpanded = !msg.sourcesExpanded">
                    {{ msg.sourcesExpanded ? '收起来源' : `查看来源（${msg.sources.length}）` }}
                  </button>
                  <div v-if="msg.sourcesExpanded" class="sources-list">
                    <div v-for="source in msg.sources" :key="source.index" class="source-item">
                      <div class="source-head"><el-tag size="small" effect="plain">[{{ source.index }}]</el-tag>
                        <el-tag size="small" :type="kbTagType(source.kb_type)" effect="plain">{{ kbLabel(source.kb_type) }}</el-tag>
                        <span class="source-name">{{ source.source || source.source_ref }}</span><span v-if="source.score" class="source-score">{{ source.score }}</span>
                      </div>
                      <div class="source-content">{{ source.content }}</div>
                    </div>
                  </div>
                </div>
                <div v-if="!msg.localError" class="msg-feedback">
                  <el-button size="small" text :disabled="msg.feedbackSubmitted" :type="msg.feedback === 'up' ? 'primary' : ''" @click="sendFeedback(msg, idx, 'up')">👍 有帮助</el-button>
                  <el-button size="small" text :disabled="msg.feedbackSubmitted" :type="msg.feedback === 'down' ? 'danger' : ''" @click="openFeedbackDialog(msg, idx)">👎 没帮助</el-button>
                  <span v-if="msg.feedbackSubmitted" class="feedback-done">反馈已保存</span><span v-if="msg.elapsed_ms" class="elapsed">{{ msg.elapsed_ms }} ms</span>
                </div>
              </template>
            </div>
          </div>
        </template>
        <div v-if="asking" class="msg-row assistant"><div class="msg-avatar">AI</div><div class="msg-bubble typing"><el-icon class="is-loading"><Loading /></el-icon>正在检索知识库并结合会话上下文生成回答…</div></div>
      </div>

      <div class="qa-input-wrap">
        <div class="qa-input">
          <el-input v-model="input" type="textarea" :autosize="{ minRows: 2, maxRows: 6 }" resize="none"
            placeholder="输入问题，Enter 发送，Shift+Enter 换行" :disabled="asking" @keydown.enter.exact.prevent="handleAsk" />
          <el-button type="primary" :loading="asking" :disabled="!input.trim()" @click="handleAsk">发送</el-button>
        </div>
        <div class="input-tip">AI 回答仅依据当前知识库，请结合引用来源核实关键结论。</div>
      </div>
    </main>

    <el-dialog v-model="feedbackDialogVisible" title="告诉我们哪里没帮助" width="480px">
      <el-input v-model="feedbackComment" type="textarea" :rows="3" placeholder="可选：答案与问题无关、引用不准确或内容已经过时…" />
      <template #footer><el-button @click="feedbackDialogVisible = false">取消</el-button><el-button type="primary" @click="confirmFeedbackDown">提交反馈</el-button></template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Delete, EditPen, Loading, Plus, Search } from '@element-plus/icons-vue'
import { knowledgeApi, projectApi } from '@/api'

interface QaSource { index: number; kb_type: string; source_ref: string; source: string; score: number; content: string }
interface ChatMsg { id?: string; role: 'user' | 'assistant'; content: string; sources?: QaSource[]; sourcesExpanded?: boolean; refused?: boolean; elapsed_ms?: number | null; feedback?: 'up' | 'down'; feedbackSubmitted?: boolean; localError?: boolean }
interface Conversation { id: string; title: string; project_id: string | null; project_name?: string | null; message_count: number; last_message_at: string | null; updated_at: string | null }

const projects = ref<Array<{ id: string; name: string }>>([])
const conversations = ref<Conversation[]>([])
const activeConversationId = ref('')
const projectFilter = ref('')
const sessionKeyword = ref('')
const sessionLoading = ref(false)
const messageLoading = ref(false)
const messages = ref<ChatMsg[]>([])
const input = ref('')
const asking = ref(false)
const msgListRef = ref<HTMLElement | null>(null)
const feedbackDialogVisible = ref(false)
const feedbackComment = ref('')
let feedbackTarget: { msg: ChatMsg; idx: number } | null = null

const activeConversation = computed(() => conversations.value.find((item) => item.id === activeConversationId.value))
const suggestions = ['登录接口应覆盖哪些异常场景？', '历史缺陷中有哪些高频问题？', '接口测试需要遵循哪些规范？']
const KB_LABELS: Record<string, string> = { document: '知识文档', defect: '缺陷', case: '用例', doc: '接口资产', term: '术语' }
function kbLabel(type: string): string { return KB_LABELS[type] || type }
function kbTagType(type: string): 'success' | 'warning' | 'danger' | 'info' | 'primary' {
  const map: Record<string, 'success' | 'warning' | 'danger' | 'info' | 'primary'> = { document: 'success', defect: 'danger', case: 'primary', doc: 'warning', term: 'info' }
  return map[type] || 'info'
}
function relativeTime(value: string | null): string {
  if (!value) return ''
  const date = new Date(value); const diff = Date.now() - date.getTime()
  if (diff < 60_000) return '刚刚'
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)} 分钟前`
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)} 小时前`
  return date.toLocaleDateString('zh-CN')
}
function mapMessage(raw: any): ChatMsg {
  return { id: raw.id, role: raw.role, content: raw.content || '', sources: raw.sources || [], sourcesExpanded: false,
    refused: !!raw.refused, elapsed_ms: raw.elapsed_ms, feedback: raw.feedback || undefined, feedbackSubmitted: !!raw.feedback }
}
function parseCitations(text: string): Array<{ type: 'text' | 'cite'; text?: string; num?: number }> {
  const result: Array<{ type: 'text' | 'cite'; text?: string; num?: number }> = []; const pattern = /\[(\d{1,2})\]/g
  let cursor = 0; let match: RegExpExecArray | null
  while ((match = pattern.exec(text)) !== null) { if (match.index > cursor) result.push({ type: 'text', text: text.slice(cursor, match.index) }); result.push({ type: 'cite', num: Number(match[1]) }); cursor = match.index + match[0].length }
  if (cursor < text.length) result.push({ type: 'text', text: text.slice(cursor) }); return result
}
function citationTooltip(msg: ChatMsg, num?: number): string { const source = msg.sources?.find((item) => item.index === num); return source ? `${source.source || source.source_ref}\n${source.content}` : '未找到对应来源' }
function scrollToBottom(): void { void nextTick(() => { if (msgListRef.value) msgListRef.value.scrollTop = msgListRef.value.scrollHeight }) }

async function loadConversations(selectFirst = false): Promise<void> {
  sessionLoading.value = true
  try {
    const res: any = await knowledgeApi.listConversations({ q: sessionKeyword.value.trim() || undefined, page: 1, page_size: 100 })
    conversations.value = res?.data?.list || []
    if (selectFirst && !activeConversationId.value && conversations.value.length) await selectConversation(conversations.value[0].id)
  } catch { conversations.value = [] } finally { sessionLoading.value = false }
}
async function selectConversation(id: string): Promise<void> {
  if (asking.value || id === activeConversationId.value) return
  activeConversationId.value = id; messageLoading.value = true
  try {
    const res: any = await knowledgeApi.getConversation(id); const data = res?.data || {}
    messages.value = (data.messages || []).map(mapMessage); projectFilter.value = data.conversation?.project_id || ''
    const index = conversations.value.findIndex((item) => item.id === id)
    if (index >= 0 && data.conversation) conversations.value[index] = { ...conversations.value[index], ...data.conversation }
    scrollToBottom()
  } catch { startNewSession() } finally { messageLoading.value = false }
}
function startNewSession(): void { if (asking.value) return; activeConversationId.value = ''; projectFilter.value = ''; messages.value = []; input.value = '' }
async function ensureConversation(): Promise<string> {
  if (activeConversationId.value) return activeConversationId.value
  const res: any = await knowledgeApi.createConversation({ project_id: projectFilter.value || undefined }); const conversation = res?.data as Conversation
  activeConversationId.value = conversation.id; conversations.value.unshift(conversation); return conversation.id
}
function useSuggestion(question: string): void { input.value = question; void handleAsk() }
async function handleAsk(): Promise<void> {
  const question = input.value.trim(); if (!question || asking.value) return
  input.value = ''; const optimisticId = `local-${Date.now()}`; messages.value.push({ id: optimisticId, role: 'user', content: question }); scrollToBottom(); asking.value = true
  try {
    const conversationId = await ensureConversation(); const res: any = await knowledgeApi.askInConversation(conversationId, { question }); const data = res?.data || {}
    const optimisticIndex = messages.value.findIndex((item) => item.id === optimisticId)
    if (optimisticIndex >= 0 && data.user_message) messages.value[optimisticIndex] = mapMessage(data.user_message)
    if (data.assistant_message) messages.value.push(mapMessage(data.assistant_message))
    const index = conversations.value.findIndex((item) => item.id === conversationId)
    if (index >= 0 && data.conversation) conversations.value[index] = { ...conversations.value[index], ...data.conversation }
    await loadConversations()
  } catch (error: any) {
    const detail = error?.response?.data?.detail || error?.message || '请稍后重试'
    messages.value.push({ id: `error-${Date.now()}`, role: 'assistant', content: `抱歉，本次回答失败：${detail}`, sources: [], localError: true })
  } finally { asking.value = false; scrollToBottom() }
}
async function renameConversation(conversation: Conversation): Promise<void> {
  try {
    const result = await ElMessageBox.prompt('请输入新的会话名称', '重命名会话', { inputValue: conversation.title, inputPattern: /\S+/, inputErrorMessage: '会话名称不能为空', confirmButtonText: '保存', cancelButtonText: '取消' })
    const title = result.value.trim(); await knowledgeApi.updateConversation(conversation.id, { title }); conversation.title = title
  } catch { /* 用户取消 */ }
}
async function removeConversation(conversation: Conversation): Promise<void> {
  try {
    await ElMessageBox.confirm(`确定删除会话“${conversation.title}”及全部消息吗？`, '删除会话', { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' })
    await knowledgeApi.removeConversation(conversation.id); conversations.value = conversations.value.filter((item) => item.id !== conversation.id)
    if (activeConversationId.value === conversation.id) startNewSession(); ElMessage.success('会话已删除')
  } catch { /* 用户取消 */ }
}
function sendFeedback(msg: ChatMsg, idx: number, rating: 'up' | 'down'): void { void submitFeedback(msg, idx, rating, '') }
function openFeedbackDialog(msg: ChatMsg, idx: number): void { feedbackTarget = { msg, idx }; feedbackComment.value = ''; feedbackDialogVisible.value = true }
async function confirmFeedbackDown(): Promise<void> { if (!feedbackTarget) return; feedbackDialogVisible.value = false; await submitFeedback(feedbackTarget.msg, feedbackTarget.idx, 'down', feedbackComment.value.trim()) }
async function submitFeedback(msg: ChatMsg, idx: number, rating: 'up' | 'down', comment: string): Promise<void> {
  if (msg.feedbackSubmitted || !msg.id || !activeConversationId.value) return
  let question = ''; for (let i = idx - 1; i >= 0; i--) { if (messages.value[i].role === 'user') { question = messages.value[i].content; break } }
  try {
    const res: any = await knowledgeApi.submitFeedback({ conversation_id: activeConversationId.value, message_id: msg.id, question, answer: msg.content, rating, comment: comment || undefined,
      retrieved: (msg.sources || []).map(({ index, kb_type, source_ref, source, score }) => ({ index, kb_type, source_ref, source, score })) })
    if (res?.code === 0) { msg.feedback = rating; msg.feedbackSubmitted = true; ElMessage.success('反馈已保存') }
  } catch { /* 请求拦截器统一展示错误 */ }
}
onMounted(async () => {
  try { const res: any = await projectApi.getList(); const data = res?.data ?? res; projects.value = Array.isArray(data) ? data : data?.list || data?.items || [] } catch { projects.value = [] }
  await loadConversations(true)
})
</script>

<style scoped>
.qa-workspace { height: calc(100vh - 104px); min-height: 620px; display: grid; grid-template-columns: 300px minmax(0, 1fr); overflow: hidden; border: 1px solid var(--el-border-color-light); border-radius: 12px; background: var(--app-bg-card); }
.session-panel { display: flex; flex-direction: column; gap: 14px; min-width: 0; padding: 18px 14px; background: var(--el-fill-color-extra-light); border-right: 1px solid var(--el-border-color-light); }
.session-panel-header,.chat-header,.source-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.panel-title,.chat-title { font-size: 17px; font-weight: 650; color: var(--el-text-color-primary); }
.panel-subtitle,.chat-subtitle { margin-top: 3px; font-size: 12px; color: var(--el-text-color-secondary); }
.session-list { flex: 1; min-height: 0; overflow-y: auto; }
.session-item { display: flex; align-items: center; gap: 4px; margin-bottom: 6px; padding: 11px 8px 11px 12px; border-radius: 9px; cursor: pointer; transition: background-color .18s ease; }
.session-item:hover { background: var(--el-fill-color-light); }.session-item.active { background: var(--el-color-primary-light-9); }
.session-main { flex: 1; min-width: 0; }.session-title { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 14px; }
.session-meta { display: flex; justify-content: space-between; gap: 8px; margin-top: 5px; color: var(--el-text-color-secondary); font-size: 11px; }.session-meta span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.session-actions { display: none; flex-shrink: 0; }.session-item:hover .session-actions,.session-item.active .session-actions { display: flex; }.session-actions :deep(.el-button) { margin: 0; padding: 5px; }
.chat-panel { display: flex; flex-direction: column; min-width: 0; min-height: 0; }.chat-header { flex-shrink: 0; padding: 17px 22px; border-bottom: 1px solid var(--el-border-color-lighter); }.chat-actions { display: flex; align-items: center; gap: 8px; }
.msg-list { flex: 1; min-height: 0; overflow-y: auto; padding: 26px clamp(20px, 5vw, 72px); }.center-state,.welcome-state { height: 100%; display: flex; align-items: center; justify-content: center; color: var(--el-text-color-secondary); }.center-state { gap: 8px; }.welcome-state { flex-direction: column; text-align: center; }
.welcome-state h2 { margin: 18px 0 6px; color: var(--el-text-color-primary); font-size: 22px; }.welcome-state p { margin: 0; font-size: 14px; }
.welcome-icon { width: 58px; height: 58px; border-radius: 18px; display: grid; place-items: center; color: white; font-weight: 700; font-size: 20px; background: linear-gradient(145deg, var(--el-color-primary), var(--el-color-primary-light-3)); box-shadow: 0 10px 26px var(--el-color-primary-light-7); }
.suggestions { display: flex; flex-wrap: wrap; justify-content: center; gap: 10px; margin-top: 26px; max-width: 720px; }.suggestions button,.sources-toggle { border: 0; cursor: pointer; color: var(--el-color-primary); background: transparent; }.suggestions button { padding: 10px 14px; border: 1px solid var(--el-border-color-light); border-radius: 20px; background: var(--app-bg-card); }.suggestions button:hover { border-color: var(--el-color-primary-light-5); background: var(--el-color-primary-light-9); }
.msg-row { display: flex; gap: 11px; margin-bottom: 20px; }.msg-row.user { flex-direction: row-reverse; }.msg-avatar { flex: 0 0 36px; height: 36px; border-radius: 11px; display: grid; place-items: center; color: white; font-size: 13px; background: var(--el-color-primary); }.msg-row.user .msg-avatar { background: var(--el-color-success); }
.msg-bubble { max-width: min(780px, 80%); padding: 12px 15px; border-radius: 10px; background: var(--el-fill-color-light); }.msg-row.user .msg-bubble { background: var(--el-color-primary-light-9); }.msg-text { font-size: 14px; line-height: 1.75; white-space: pre-wrap; word-break: break-word; }.typing { display: flex; align-items: center; gap: 8px; color: var(--el-text-color-secondary); }.cite-tag { margin: 0 1px; cursor: help; color: var(--el-color-primary); font-weight: 650; }
.msg-sources { margin-top: 10px; padding-top: 8px; border-top: 1px dashed var(--el-border-color); }.sources-toggle { padding: 0; font-size: 12px; }.sources-list { margin-top: 8px; }.source-item { margin-bottom: 7px; padding: 9px 11px; border: 1px solid var(--el-border-color-lighter); border-radius: 7px; background: var(--app-bg-card); font-size: 12px; }.source-head { justify-content: flex-start; }.source-name { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-weight: 500; }.source-score { margin-left: auto; color: var(--el-text-color-secondary); }.source-content { margin-top: 6px; color: var(--el-text-color-regular); line-height: 1.55; white-space: pre-wrap; word-break: break-word; }
.msg-feedback { display: flex; align-items: center; gap: 2px; margin-top: 8px; }.feedback-done { margin-left: 6px; color: var(--el-color-success); font-size: 12px; }.elapsed { margin-left: auto; color: var(--el-text-color-secondary); font-size: 11px; }
.qa-input-wrap { flex-shrink: 0; padding: 14px clamp(20px, 5vw, 72px) 16px; border-top: 1px solid var(--el-border-color-lighter); }.qa-input { display: flex; align-items: flex-end; gap: 10px; }.qa-input :deep(.el-textarea__inner) { min-height: 58px !important; border-radius: 10px; }.qa-input .el-button { height: 42px; min-width: 76px; }.input-tip { margin-top: 7px; text-align: center; color: var(--el-text-color-secondary); font-size: 11px; }
@media (max-width: 900px) { .qa-workspace { grid-template-columns: 230px minmax(0, 1fr); }.chat-header { align-items: flex-start; }.chat-actions { flex-direction: column; align-items: flex-end; }.msg-bubble { max-width: 88%; } }
</style>
