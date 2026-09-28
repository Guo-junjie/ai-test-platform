<template>
  <div class="schedule-page">
    <PageHeader title="定时回归" description="用可视化规则安排测试计划，系统自动计算触发时间并绑定已发布测试环境。">
      <template #actions><el-select v-model="projectId" filterable placeholder="选择项目" @change="changeProject"><el-option v-for="p in projects" :key="p.id" :label="p.name" :value="p.id" /></el-select><el-button type="primary" @click="openCreate">新建任务</el-button></template>
    </PageHeader>

    <el-card shadow="never">
      <div class="filters"><el-input v-model="keyword" clearable placeholder="搜索任务名称" /><el-select v-model="statusFilter" clearable placeholder="全部状态"><el-option label="运行中" value="active"/><el-option label="已暂停" value="paused"/></el-select></div>
      <el-table :data="filteredTasks" v-loading="loading">
        <el-table-column label="任务" min-width="210"><template #default="{row}"><b>{{row.name}}</b><div class="muted">{{row.description||'暂无说明'}}</div></template></el-table-column>
        <el-table-column label="执行规则" min-width="180"><template #default="{row}">{{scheduleLabel(row.cron_expression)}}<div class="muted">Asia/Shanghai</div></template></el-table-column>
        <el-table-column label="测试目标" min-width="180"><template #default="{row}">{{targetLabel(row.target_type)}}<div class="muted">{{row.target_name||targetName(row)}}</div></template></el-table-column>
        <el-table-column label="环境" min-width="150"><template #default="{row}">{{row.env_config?.environment_name||'未绑定'}}</template></el-table-column>
        <el-table-column label="下次执行" width="175"><template #default="{row}">{{row.next_run_at?formatTime(row.next_run_at):'保存后自动计算'}}</template></el-table-column>
        <el-table-column label="状态" width="90"><template #default="{row}"><StatusPill :status="row.status" :map="taskStatusMap"/></template></el-table-column>
        <el-table-column label="操作" width="225" fixed="right"><template #default="{row}"><el-button text @click="viewHistory(row)">历史</el-button><el-button text type="primary" @click="openEdit(row)">编辑</el-button><el-button text :type="row.status==='active'?'warning':'success'" @click="toggleTask(row)">{{row.status==='active'?'暂停':'启用'}}</el-button><el-button text type="danger" @click="removeTask(row)">删除</el-button></template></el-table-column>
      </el-table>
      <el-empty v-if="projectId&&!loading&&!filteredTasks.length" description="暂无符合条件的定时任务"><el-button type="primary" @click="openCreate">创建第一个定时任务</el-button></el-empty>
      <el-empty v-if="!projectId" description="请选择项目后查看定时回归任务" />
    </el-card>

    <el-drawer v-model="editorVisible" :title="editingId?'编辑定时任务':'新建定时任务'" size="min(880px, 96vw)" destroy-on-close>
      <div class="editor-grid">
        <el-form label-position="top">
          <el-form-item label="任务名称" required><el-input v-model="form.name" placeholder="例如：订单核心链路每日回归" /></el-form-item>
          <el-form-item label="说明"><el-input v-model="form.description" type="textarea" :rows="2" /></el-form-item>
          <el-form-item label="何时运行" required><SchedulePicker :value="form.schedule" @change="updateSchedule" /></el-form-item>
          <el-divider content-position="left">运行内容</el-divider>
          <div class="two-columns"><el-form-item label="目标类型" required><el-select v-model="form.target_type" @change="targetChanged"><el-option label="测试计划" value="plan"/><el-option label="测试场景" value="scenario"/><el-option label="已批准用例集合" value="case_collection"/></el-select></el-form-item><el-form-item v-if="form.target_type!=='case_collection'" label="测试目标" required><el-select v-model="form.target_id" filterable :loading="targetsLoading" placeholder="请选择"><el-option v-for="item in targets" :key="item.id" :label="item.name" :value="item.id"/></el-select></el-form-item></div>
          <el-form-item label="执行环境" required><el-select v-model="form.environment_id" filterable placeholder="选择已发布环境"><el-option v-for="env in environments" :key="env.id" :label="`${env.name} · ${env.base_url}`" :value="env.id" :disabled="env.status!=='published'"/></el-select><div class="form-tip">定时任务只使用环境档案中的地址与凭证，不再手工填写服务 URL。</div></el-form-item>
          <el-form-item label="创建后状态"><el-radio-group v-model="form.status"><el-radio-button value="active">立即启用</el-radio-button><el-radio-button value="paused">先保存为暂停</el-radio-button></el-radio-group></el-form-item>
        </el-form>
        <aside class="preview-card" v-loading="previewing">
          <h3>调度预览</h3><p>{{previewDescription}}</p>
          <div class="cron-note"><span>系统调度规则</span><code>{{cronExpression||'计算中…'}}</code></div>
          <h4>后续 5 次触发</h4><ol><li v-for="item in nextRuns" :key="item">{{formatTime(item)}}</li></ol>
          <el-alert v-if="selectedEnvironment" :type="selectedEnvironment.status==='published'?'success':'warning'" :closable="false" :title="selectedEnvironment.status==='published'?'环境已发布，可用于无人值守执行':'该环境尚未发布'" :description="selectedEnvironment.base_url" show-icon />
        </aside>
      </div>
      <template #footer><el-button @click="editorVisible=false">取消</el-button><el-button type="primary" :loading="submitting" @click="submit">{{editingId?'保存修改':'创建任务'}}</el-button></template>
    </el-drawer>

    <el-drawer v-model="historyVisible" title="执行历史" size="680px"><el-table :data="history" v-loading="historyLoading"><el-table-column label="状态" width="100"><template #default="{row}"><StatusPill :status="row.status"/></template></el-table-column><el-table-column label="开始时间" width="180"><template #default="{row}">{{formatTime(row.started_at)}}</template></el-table-column><el-table-column label="结束时间" width="180"><template #default="{row}">{{row.finished_at?formatTime(row.finished_at):'—'}}</template></el-table-column><el-table-column prop="error_message" label="结果说明" show-overflow-tooltip/></el-table><el-empty v-if="!historyLoading&&!history.length" description="暂无执行历史"/></el-drawer>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import dayjs from 'dayjs'
import { ElMessage, ElMessageBox } from 'element-plus'
import { environmentApi, planApi, projectApi, scenarioApi, scheduledTaskApi } from '@/api'
import PageHeader from '@/components/PageHeader.vue'
import SchedulePicker, { type ScheduleValue } from '@/components/SchedulePicker.vue'
import StatusPill from '@/components/StatusPill.vue'

const projectId=ref(''),projects=ref<any[]>([]),tasks=ref<any[]>([]),loading=ref(false),keyword=ref(''),statusFilter=ref('')
const editorVisible=ref(false),editingId=ref(''),submitting=ref(false),previewing=ref(false),cronExpression=ref(''),nextRuns=ref<string[]>([])
const targets=ref<any[]>([]),targetsLoading=ref(false),environments=ref<any[]>([])
const historyVisible=ref(false),historyLoading=ref(false),history=ref<any[]>([])
const taskStatusMap={active:{label:'运行中',type:'success'},paused:{label:'已暂停',type:'info'}} as any
const form=reactive({name:'',description:'',target_type:'plan',target_id:'',environment_id:'',status:'active',schedule:{mode:'daily',hour:9,minute:0,weekday:1,monthDay:1,intervalHours:2,timezone:'Asia/Shanghai'} as ScheduleValue})
const filteredTasks=computed(()=>tasks.value.filter(x=>(!keyword.value||x.name?.includes(keyword.value))&&(!statusFilter.value||x.status===statusFilter.value)))
const selectedEnvironment=computed(()=>environments.value.find(x=>x.id===form.environment_id))
const previewDescription=computed(()=>{const t=String(form.schedule.hour).padStart(2,'0')+':'+String(form.schedule.minute).padStart(2,'0');if(form.schedule.mode==='weekly')return `每周${['日','一','二','三','四','五','六'][form.schedule.weekday]} ${t} 执行`;if(form.schedule.mode==='monthly')return `每月 ${form.schedule.monthDay} 日 ${t} 执行`;if(form.schedule.mode==='interval')return `每 ${form.schedule.intervalHours} 小时执行一次`;return `每天 ${t} 执行`})
function formatTime(t:string){return t?dayjs(t).format('YYYY-MM-DD HH:mm:ss'):'—'}
function targetLabel(t:string){return({plan:'测试计划',scenario:'测试场景',case_collection:'用例集合'} as any)[t]||t}
function targetName(row:any){return row.target_type==='case_collection'?'全部已批准 API 用例':row.target_id?'已选择目标':'未选择'}
function scheduleLabel(cron:string){const p=String(cron||'').split(' ');if(p.length!==5)return'自定义规则';if(p[1]?.startsWith('*/'))return`每 ${p[1].slice(2)} 小时`;if(p[4]!=='*')return`每周${['日','一','二','三','四','五','六'][Number(p[4])]} ${String(p[1]).padStart(2,'0')}:${String(p[0]).padStart(2,'0')}`;if(p[2]!=='*')return`每月 ${p[2]} 日 ${String(p[1]).padStart(2,'0')}:${String(p[0]).padStart(2,'0')}`;return`每天 ${String(p[1]).padStart(2,'0')}:${String(p[0]).padStart(2,'0')}`}
function cronToSchedule(cron:string):ScheduleValue{const p=String(cron||'0 9 * * *').split(' ');const base={mode:'daily',hour:Number(p[1])||0,minute:Number(p[0])||0,weekday:1,monthDay:1,intervalHours:2,timezone:'Asia/Shanghai'};if(p[1]?.startsWith('*/'))return{...base,mode:'interval',hour:0,intervalHours:Number(p[1].slice(2))||2};if(p[4]!=='*')return{...base,mode:'weekly',weekday:Number(p[4])||0};if(p[2]!=='*')return{...base,mode:'monthly',monthDay:Number(p[2])||1};return base}
async function loadProjects(){const r:any=await projectApi.getList();projects.value=Array.isArray(r?.data)?r.data:(r?.data?.items||r?.data?.list||[]);projectId.value=projects.value[0]?.id||'';if(projectId.value)await changeProject()}
async function changeProject(){await Promise.all([loadTasks(),loadEnvironments(),loadTargets()])}
async function loadTasks(){loading.value=true;try{const r:any=await scheduledTaskApi.listTasks(projectId.value);tasks.value=r?.data?.items||r?.data?.list||(Array.isArray(r?.data)?r.data:[])}finally{loading.value=false}}
async function loadEnvironments(){const r:any=await environmentApi.list(projectId.value);environments.value=r?.data?.items||r?.data?.list||(Array.isArray(r?.data)?r.data:[])}
async function loadTargets(){targetsLoading.value=true;try{if(form.target_type==='plan'){const r:any=await planApi.list({project_id:projectId.value,page:1,page_size:200});targets.value=r?.data?.items||r?.data?.list||[]}else if(form.target_type==='scenario'){const r:any=await scenarioApi.list({project_id:projectId.value,page:1,page_size:200});targets.value=r?.data?.items||r?.data?.list||[]}else targets.value=[]}finally{targetsLoading.value=false}}
async function targetChanged(){form.target_id='';await loadTargets()}
function reset(){Object.assign(form,{name:'',description:'',target_type:'plan',target_id:'',environment_id:'',status:'active',schedule:{mode:'daily',hour:9,minute:0,weekday:1,monthDay:1,intervalHours:2,timezone:'Asia/Shanghai'}});cronExpression.value='';nextRuns.value=[]}
async function openCreate(){if(!projectId.value){ElMessage.warning('请先选择项目');return}editingId.value='';reset();await loadTargets();editorVisible.value=true;await preview()}
async function openEdit(row:any){editingId.value=row.id;Object.assign(form,{name:row.name,description:row.description||'',target_type:row.target_type,target_id:row.target_id||'',environment_id:row.env_config?.environment_id||'',status:row.status,schedule:cronToSchedule(row.cron_expression)});await loadTargets();editorVisible.value=true;await preview()}
async function updateSchedule(v:ScheduleValue){form.schedule=v;await preview()}
async function preview(){previewing.value=true;try{const s=form.schedule;const r:any=await scheduledTaskApi.preview({mode:s.mode,hour:s.hour,minute:s.minute,weekday:s.weekday,month_day:s.monthDay,interval_hours:s.intervalHours,timezone:s.timezone,count:5});cronExpression.value=r?.data?.cron_expression||'';nextRuns.value=r?.data?.next_runs||[]}finally{previewing.value=false}}
async function submit(){if(!form.name.trim()||!cronExpression.value){ElMessage.warning('请填写任务名称并确认调度规则');return}if(form.target_type!=='case_collection'&&!form.target_id){ElMessage.warning('请选择测试目标');return}const env=selectedEnvironment.value;if(!env||env.status!=='published'){ElMessage.warning('请选择已发布的执行环境');return}submitting.value=true;try{const payload:any={name:form.name.trim(),description:form.description,cron_expression:cronExpression.value,nl_schedule:previewDescription.value,target_type:form.target_type,target_id:form.target_id||null,status:form.status,env_config:{environment_id:env.id,environment_name:env.name,service_url:env.base_url}};if(editingId.value)await scheduledTaskApi.updateTask(editingId.value,payload);else await scheduledTaskApi.createTask({...payload,project_id:projectId.value});ElMessage.success(editingId.value?'任务已更新':'定时任务已创建');editorVisible.value=false;await loadTasks()}finally{submitting.value=false}}
async function toggleTask(row:any){await scheduledTaskApi.toggleTask(row.id);ElMessage.success(row.status==='active'?'任务已暂停':'任务已启用');await loadTasks()}
async function removeTask(row:any){try{await ElMessageBox.confirm(`确认删除「${row.name}」吗？`,'删除任务',{type:'warning'})}catch{return}await scheduledTaskApi.deleteTask(row.id);ElMessage.success('任务已删除');await loadTasks()}
async function viewHistory(row:any){historyVisible.value=true;historyLoading.value=true;try{const r:any=await scheduledTaskApi.getHistory(row.id);history.value=r?.data?.items||r?.data?.list||(Array.isArray(r?.data)?r.data:[])}finally{historyLoading.value=false}}
onMounted(loadProjects)
</script>

<style scoped>
.schedule-page{display:grid;gap:16px}.schedule-page :deep(.page-actions .el-select){width:220px}.filters{display:flex;gap:10px;margin-bottom:14px}.filters .el-input{width:280px}.filters .el-select{width:150px}.muted{margin-top:4px;color:var(--app-text-secondary);font-size:12px}.editor-grid{display:grid;grid-template-columns:minmax(0,1.6fr) minmax(290px,1fr);gap:22px}.two-columns{display:grid;grid-template-columns:1fr 1.4fr;gap:12px}.two-columns .el-select,.editor-grid .el-form>.el-form-item .el-select{width:100%}.form-tip{margin-top:6px;color:var(--app-text-secondary);font-size:12px}.preview-card{position:sticky;top:0;height:max-content;padding:20px;border:1px solid var(--el-border-color-light);border-radius:10px;background:var(--el-fill-color-lighter)}.preview-card h3{margin-top:0}.preview-card p{color:var(--el-color-primary);font-weight:600}.preview-card ol{padding-left:22px;line-height:2}.cron-note{display:grid;gap:5px;margin:16px 0;padding:10px;background:white;border-radius:7px}.cron-note span{font-size:12px;color:var(--app-text-secondary)}@media(max-width:780px){.editor-grid{grid-template-columns:1fr}.preview-card{position:static}.two-columns{grid-template-columns:1fr}.filters{flex-wrap:wrap}}
</style>
