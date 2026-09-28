<template>
  <div class="script-page">
    <PageHeader title="脚本生成" description="生成、校验并绑定前置、后置或 SQL 验证脚本。">
      <template #actions><el-select v-model="projectId" filterable placeholder="选择项目" @change="changeProject"><el-option v-for="p in projects" :key="p.id" :label="p.name" :value="p.id"/></el-select><el-button type="primary" :loading="generating" @click="generate">生成脚本</el-button><el-button :disabled="!selected" @click="download">下载</el-button><el-button :disabled="!selected?.id" :loading="validating" @click="validate">安全试运行</el-button></template>
    </PageHeader>
    <div class="script-grid">
      <el-card shadow="never" class="script-list"><template #header><b>脚本资产</b></template><button v-for="item in scripts" :key="item.id" type="button" :class="{active:selected?.id===item.id}" @click="selected=item"><span><b>{{typeLabel(item.script_type)}}</b><small>{{item.nl_input||'未填写说明'}}</small></span><time>{{formatTime(item.created_at)}}</time></button><el-empty v-if="!scripts.length" description="暂无脚本，填写右侧需求后生成" :image-size="60"/><el-pagination v-if="total>pageSize" v-model:current-page="page" :page-size="pageSize" :total="total" layout="prev,next" @current-change="loadScripts"/></el-card>
      <el-card shadow="never"><template #header><div class="editor-head"><div><b>{{selected?typeLabel(selected.script_type):'新脚本'}}</b><el-tag v-if="runResult" :type="runResult.valid?'success':'danger'">{{runResult.valid?'最近校验通过':'最近校验失败'}}</el-tag></div><el-button v-if="selected" text type="primary" @click="copy">复制代码</el-button></div></template>
        <el-form label-position="top" class="config-form"><div class="form-row"><el-form-item label="脚本类型"><el-radio-group v-model="scriptType"><el-radio-button value="pre_script">前置脚本</el-radio-button><el-radio-button value="post_script">后置脚本</el-radio-button><el-radio-button value="sql_script">SQL 验证</el-radio-button></el-radio-group></el-form-item><el-form-item label="绑定用例"><el-select v-model="caseId" clearable filterable placeholder="可选"><el-option v-for="c in cases" :key="c.id" :label="c.title" :value="c.id"/></el-select></el-form-item></div><el-form-item label="生成需求"><el-input v-model="nlInput" type="textarea" :rows="3" placeholder="例如：测试前创建一个随机用户，并把用户 ID 写入变量"/></el-form-item></el-form>
        <pre class="code"><code>{{selected?.code||'# 生成后在这里查看脚本内容'}}</code></pre>
        <el-alert v-if="runResult" :type="runResult.valid?'success':'error'" :closable="false" show-icon :title="runResult.detail||runResult.message" :description="runResult.message"/>
      </el-card>
    </div>
  </div>
</template>
<script setup lang="ts">
import { onMounted, ref } from 'vue'
import dayjs from 'dayjs'
import { ElMessage } from 'element-plus'
import { caseApi, projectApi, scriptsApi } from '@/api'
import PageHeader from '@/components/PageHeader.vue'
const projectId=ref(''),projects=ref<any[]>([]),cases=ref<any[]>([]),scripts=ref<any[]>([]),selected=ref<any>(null),total=ref(0),page=ref(1),pageSize=20
const scriptType=ref('pre_script'),caseId=ref(''),nlInput=ref(''),generating=ref(false),validating=ref(false),runResult=ref<any>(null)
function typeLabel(v:string){return({pre_script:'前置脚本',post_script:'后置脚本',sql_script:'SQL 验证脚本'} as any)[v]||v}function formatTime(v:string){return v?dayjs(v).format('MM-DD HH:mm'):'—'}
async function loadProjects(){const r:any=await projectApi.getList();projects.value=r?.data?.items||r?.data?.list||[];projectId.value=projects.value[0]?.id||'';if(projectId.value)await changeProject()}
async function changeProject(){page.value=1;selected.value=null;runResult.value=null;const [c]=await Promise.all([caseApi.list({project_id:projectId.value,page:1,page_size:200}),loadScripts()]) as any[];cases.value=c?.data?.items||[]}
async function loadScripts(){if(!projectId.value)return;const r:any=await scriptsApi.list(projectId.value,{page:page.value,page_size:pageSize});scripts.value=r?.data?.items||[];total.value=r?.data?.total||0;if(!selected.value&&scripts.value.length)selected.value=scripts.value[0]}
async function generate(){if(!projectId.value||!nlInput.value.trim()){ElMessage.warning('请选择项目并填写生成需求');return}generating.value=true;try{const r:any=await scriptsApi.generateScript({project_id:projectId.value,script_type:scriptType.value,nl_input:nlInput.value.trim(),case_id:caseId.value||null,context:{}});const d=r?.data||{};selected.value={...d,code:d.code,script_type:scriptType.value,nl_input:nlInput.value,created_at:new Date().toISOString()};runResult.value={valid:d.valid,detail:d.error||'生成脚本已通过语法与安全检查',message:d.bound_case_id?'已同步绑定到所选用例':'尚未绑定用例'};ElMessage.success(d.degraded?'AI 不可用，已使用规则模板生成':'脚本生成完成');await loadScripts()}finally{generating.value=false}}
async function validate(){validating.value=true;try{const r:any=await scriptsApi.validate(selected.value.id);runResult.value=r?.data;ElMessage.success(runResult.value.valid?'安全试运行通过':'安全试运行未通过')}finally{validating.value=false}}
function download(){const blob=new Blob([selected.value.code],{type:'text/plain;charset=utf-8'});const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download=`${typeLabel(selected.value.script_type)}.${selected.value.language==='sql'?'sql':'py'}`;a.click();URL.revokeObjectURL(url)}
async function copy(){await navigator.clipboard.writeText(selected.value.code);ElMessage.success('已复制')}
onMounted(loadProjects)
</script>
<style scoped>
.script-page{display:grid;gap:16px}.script-page :deep(.page-actions .el-select){width:210px}.script-grid{display:grid;grid-template-columns:300px minmax(0,1fr);gap:16px}.script-list button{width:100%;display:grid;grid-template-columns:1fr auto;gap:8px;padding:12px 10px;border:0;border-bottom:1px solid var(--el-border-color-lighter);background:none;text-align:left;cursor:pointer}.script-list button.active{background:var(--el-color-primary-light-9);border-left:3px solid var(--el-color-primary)}.script-list span{display:grid;gap:4px}.script-list small,.script-list time{color:var(--app-text-secondary);font-size:11px}.editor-head{display:flex;justify-content:space-between}.editor-head>div{display:flex;gap:10px;align-items:center}.form-row{display:grid;grid-template-columns:1.4fr 1fr;gap:14px}.form-row .el-select{width:100%}.code{min-height:390px;max-height:560px;margin:8px 0 14px;padding:18px;overflow:auto;border-radius:8px;background:#0f172a;color:#dbeafe;font:13px/1.65 ui-monospace,SFMono-Regular,Menlo,monospace}@media(max-width:850px){.script-grid{grid-template-columns:1fr}.form-row{grid-template-columns:1fr}}
</style>
