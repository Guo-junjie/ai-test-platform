<template>
  <div class="gate-page">
    <PageHeader title="质量门禁" description="把发布标准配置为可执行规则，测试结束后自动评估并保留审计结果。">
      <template #actions><el-select v-model="projectId" filterable placeholder="选择项目" @change="loadAll"><el-option v-for="p in projects" :key="p.id" :label="p.name" :value="p.id"/></el-select><el-button type="primary" @click="openRule()">新增规则</el-button></template>
    </PageHeader>

    <div class="summary-grid">
      <el-card shadow="never"><span>门禁状态</span><div><el-switch v-model="config.enabled" @change="saveConfig"/><b>{{config.enabled?'已启用':'已停用'}}</b></div></el-card>
      <el-card shadow="never"><span>上线策略</span><div><el-switch v-model="config.block_deployment" @change="saveConfig"/><b>{{config.block_deployment?'失败时阻断':'仅记录结果'}}</b></div></el-card>
      <el-card shadow="never"><span>失败通知</span><div><el-switch v-model="config.notify_on_fail" @change="saveConfig"/><b>{{config.notify_on_fail?'已开启':'已关闭'}}</b></div></el-card>
      <el-card shadow="never"><span>已启用规则</span><strong>{{rules.filter(x=>x.enabled).length}}</strong></el-card>
    </div>

    <div class="gate-grid">
      <el-card shadow="never" v-loading="loading">
        <template #header><div class="card-head"><div><b>门禁规则</b><p>规则可应用于全部计划，也可只约束指定计划。</p></div></div></template>
        <el-table :data="rules" row-key="id">
          <el-table-column label="规则" min-width="190"><template #default="{row}"><b>{{row.name}}</b><div class="muted">{{metricUnit(row.metric)}}</div></template></el-table-column>
          <el-table-column label="通过条件" width="145"><template #default="{row}"><code>{{operatorLabel(row.operator)}} {{row.threshold}}{{unit(row.metric)}}</code></template></el-table-column>
          <el-table-column label="适用范围" min-width="160"><template #default="{row}">{{scopeLabel(row.plan_ids)}}</template></el-table-column>
          <el-table-column label="最近实测" width="130"><template #default="{row}"><template v-if="previewMap[row.metric]?.actual!==null&&previewMap[row.metric]?.actual!==undefined"><b>{{previewMap[row.metric].actual}}{{unit(row.metric)}}</b><el-tag size="small" :type="previewMap[row.metric].passed?'success':'danger'">{{previewMap[row.metric].passed?'通过':'未通过'}}</el-tag></template><span v-else class="muted">暂无数据</span></template></el-table-column>
          <el-table-column label="启用" width="75"><template #default="{row}"><el-switch v-model="row.enabled" @change="saveRule(row)"/></template></el-table-column>
          <el-table-column label="操作" width="120"><template #default="{row}"><el-button text type="primary" @click="openRule(row)">编辑</el-button><el-button text type="danger" @click="disableRule(row)">停用</el-button></template></el-table-column>
        </el-table>
        <el-empty v-if="!loading&&!rules.length" description="暂无门禁规则"><el-button type="primary" @click="openRule()">创建第一条规则</el-button></el-empty>
      </el-card>

      <el-card shadow="never" class="preview-card">
        <template #header><div class="card-head"><div><b>实时预览</b><p>基于最近一次测试报告，仅用于配置校验。</p></div><el-button text type="primary" @click="loadPreview">刷新</el-button></div></template>
        <el-alert v-if="previewRunId" :type="allPreviewPassed?'success':'warning'" :closable="false" show-icon :title="allPreviewPassed?'当前配置可通过最近一次运行':'当前配置会阻断最近一次运行'" />
        <el-empty v-else description="暂无测试报告，运行测试后可在这里预览门禁结果" :image-size="70" />
        <div v-if="previewRunId" class="preview-list"><div v-for="row in previewItems" :key="row.metric"><span>{{row.name}}</span><b>{{row.actual??'—'}}{{row.actual===null?'':unit(row.metric)}}</b><el-icon :class="row.passed?'ok':'bad'"><CircleCheckFilled v-if="row.passed"/><CircleCloseFilled v-else/></el-icon></div></div>
      </el-card>
    </div>

    <el-card shadow="never">
      <template #header><div class="card-head"><div><b>最近评估结果</b><p>每次运行的门禁判断均保留，可追溯到具体运行。</p></div></div></template>
      <el-table :data="history" v-loading="historyLoading"><el-table-column label="评估时间" width="180"><template #default="{row}">{{formatTime(row.created_at)}}</template></el-table-column><el-table-column label="运行" min-width="180"><template #default="{row}"><el-link type="primary" @click="$router.push(`/runs/${row.test_run_id}`)">{{row.test_run_id.slice(0,8)}}</el-link></template></el-table-column><el-table-column prop="quality_score" label="质量分" width="100"/><el-table-column label="结果" width="110"><template #default="{row}"><el-tag :type="row.gate_passed?'success':'danger'">{{row.gate_passed?'通过':'未通过'}}</el-tag></template></el-table-column><el-table-column label="违规项"><template #default="{row}">{{row.gate_details?.violations?.map((x:any)=>x.message).join('；')||'无'}}</template></el-table-column></el-table>
      <el-pagination v-if="historyTotal>20" v-model:current-page="page" :total="historyTotal" :page-size="20" layout="prev,pager,next,total" @current-change="loadHistory"/>
    </el-card>

    <el-dialog v-model="ruleVisible" :title="editingRule?'编辑门禁规则':'新增门禁规则'" width="620px">
      <el-form label-position="top">
        <el-form-item label="指标" required><el-select v-model="ruleForm.metric" :disabled="!!editingRule"><el-option v-for="item in metricOptions" :key="item.value" :label="item.label" :value="item.value"/></el-select></el-form-item>
        <el-form-item label="规则名称"><el-input v-model="ruleForm.name"/></el-form-item>
        <div class="condition-row"><el-form-item label="比较方式" required><el-select v-model="ruleForm.operator"><el-option v-for="item in operatorOptions" :key="item.value" :label="item.label" :value="item.value"/></el-select></el-form-item><el-form-item label="阈值" required><el-input-number v-model="ruleForm.threshold" :min="0" :max="100"/></el-form-item></div>
        <el-form-item label="适用测试计划"><el-select v-model="ruleForm.plan_ids" multiple clearable filterable placeholder="留空表示全部计划"><el-option v-for="p in plans" :key="p.id" :label="p.name" :value="p.id"/></el-select></el-form-item>
        <el-form-item label="启用规则"><el-switch v-model="ruleForm.enabled"/></el-form-item>
      </el-form>
      <template #footer><el-button @click="ruleVisible=false">取消</el-button><el-button type="primary" :loading="saving" @click="submitRule">保存规则</el-button></template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import dayjs from 'dayjs'
import { CircleCheckFilled, CircleCloseFilled } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { planApi, projectApi, qualityGateApi } from '@/api'
import PageHeader from '@/components/PageHeader.vue'

const projectId=ref(''),projects=ref<any[]>([]),plans=ref<any[]>([]),rules=ref<any[]>([]),loading=ref(false),saving=ref(false)
const history=ref<any[]>([]),historyLoading=ref(false),historyTotal=ref(0),page=ref(1)
const previewItems=ref<any[]>([]),previewRunId=ref(''),ruleVisible=ref(false),editingRule=ref<any>(null)
const config=reactive({enabled:true,block_deployment:true,notify_on_fail:true,notify_channels:['webhook'] as string[]})
const ruleForm=reactive({metric:'min_api_pass_rate',name:'API 测试通过率',operator:'>=',threshold:90,plan_ids:[] as string[],enabled:true})
const metricOptions=[{label:'P0 缺陷数',value:'max_p0_defects'},{label:'P1 缺陷数',value:'max_p1_defects'},{label:'API 测试通过率',value:'min_api_pass_rate'},{label:'性能测试通过率',value:'min_performance_pass_rate'},{label:'集成测试通过率',value:'min_integration_pass_rate'},{label:'质量评分',value:'min_quality_score'}]
const operatorOptions=[{label:'小于等于',value:'<='},{label:'大于等于',value:'>='},{label:'小于',value:'<'},{label:'大于',value:'>'},{label:'等于',value:'=='},{label:'不等于',value:'!='}]
const previewMap=computed(()=>Object.fromEntries(previewItems.value.map(x=>[x.metric,x])))
const allPreviewPassed=computed(()=>previewItems.value.filter(x=>x.enabled&&x.passed!==null).every(x=>x.passed))
function unit(metric:string){return metric.includes('rate')?'%':''}function metricUnit(metric:string){return metric.includes('rate')?'百分比':metric.includes('defects')?'缺陷数量':'评分'}
function operatorLabel(op:string){return({'>=':'至少','<=':'不超过','>':'大于','<':'小于','==':'等于','!=':'不等于'} as any)[op]||op}
function scopeLabel(ids:string[]){if(!ids?.length)return'全部测试计划';const names=plans.value.filter(x=>ids.includes(x.id)).map(x=>x.name);return names.join('、')||`${ids.length} 个指定计划`}
function formatTime(t:string){return t?dayjs(t).format('YYYY-MM-DD HH:mm:ss'):'—'}
async function loadProjects(){const r:any=await projectApi.getList();projects.value=Array.isArray(r?.data)?r.data:(r?.data?.items||r?.data?.list||[]);projectId.value=projects.value[0]?.id||'';if(projectId.value)await loadAll()}
async function loadAll(){loading.value=true;try{const [c,r,p]=await Promise.all([qualityGateApi.getConfig(projectId.value),qualityGateApi.listRules(projectId.value),planApi.list({project_id:projectId.value,page:1,page_size:200})]);Object.assign(config,c?.data||{});rules.value=r?.data?.items||[];plans.value=p?.data?.items||p?.data?.list||[];await Promise.all([loadPreview(),loadHistory()])}finally{loading.value=false}}
async function saveConfig(){await qualityGateApi.updateConfig(projectId.value,{...config,rules:Object.fromEntries(rules.value.map(x=>[x.metric,x.threshold]))});ElMessage.success('门禁策略已保存')}
async function loadPreview(){const r:any=await qualityGateApi.previewRules(projectId.value);previewItems.value=r?.data?.items||[];previewRunId.value=r?.data?.run_id||''}
async function loadHistory(){historyLoading.value=true;try{const r:any=await qualityGateApi.getHistory(projectId.value,{page:page.value,page_size:20});history.value=r?.data?.list||[];historyTotal.value=r?.data?.total||0}finally{historyLoading.value=false}}
function openRule(row?:any){editingRule.value=row||null;if(row)Object.assign(ruleForm,{metric:row.metric,name:row.name,operator:row.operator,threshold:row.threshold,plan_ids:[...(row.plan_ids||[])],enabled:row.enabled});else Object.assign(ruleForm,{metric:'min_api_pass_rate',name:'API 测试通过率',operator:'>=',threshold:90,plan_ids:[],enabled:true});ruleVisible.value=true}
async function submitRule(){saving.value=true;try{const payload={project_id:projectId.value,...ruleForm};if(editingRule.value)await qualityGateApi.updateRule(ruleForm.metric,payload);else await qualityGateApi.saveRule(payload);ElMessage.success('规则已保存');ruleVisible.value=false;await Promise.all([loadRules(),loadPreview()])}finally{saving.value=false}}
async function loadRules(){const r:any=await qualityGateApi.listRules(projectId.value);rules.value=r?.data?.items||[]}
async function saveRule(row:any){await qualityGateApi.updateRule(row.id,{project_id:projectId.value,metric:row.metric,name:row.name,operator:row.operator,threshold:row.threshold,plan_ids:row.plan_ids||[],enabled:row.enabled});ElMessage.success(row.enabled?'规则已启用':'规则已停用');await loadPreview()}
async function disableRule(row:any){row.enabled=false;await saveRule(row)}
onMounted(loadProjects)
</script>

<style scoped>
.gate-page{display:grid;gap:16px}.gate-page :deep(.page-actions .el-select){width:220px}.summary-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}.summary-grid .el-card :deep(.el-card__body){display:grid;gap:10px}.summary-grid span{font-size:12px;color:var(--app-text-secondary)}.summary-grid div{display:flex;align-items:center;gap:10px}.summary-grid strong{font-size:26px}.gate-grid{display:grid;grid-template-columns:minmax(0,2fr) minmax(300px,1fr);gap:16px}.card-head{display:flex;justify-content:space-between}.card-head p{margin:5px 0 0;color:var(--app-text-secondary);font-size:12px}.muted{color:var(--app-text-secondary);font-size:12px}.el-tag{margin-left:6px}.preview-list{display:grid;gap:0;margin-top:14px}.preview-list>div{display:grid;grid-template-columns:1fr auto 22px;gap:8px;align-items:center;padding:11px 0;border-bottom:1px solid var(--el-border-color-lighter)}.ok{color:var(--el-color-success)}.bad{color:var(--el-color-danger)}.condition-row{display:grid;grid-template-columns:1fr 1fr;gap:12px}.condition-row .el-select,.condition-row .el-input-number,.el-dialog .el-select{width:100%}.el-pagination{justify-content:flex-end;margin-top:14px}@media(max-width:1000px){.summary-grid{grid-template-columns:1fr 1fr}.gate-grid{grid-template-columns:1fr}}@media(max-width:560px){.summary-grid{grid-template-columns:1fr}}
</style>
