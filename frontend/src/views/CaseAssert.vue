<template>
  <div class="assert-page" v-loading="loading">
    <PageHeader title="断言配置" :description="item?.title || '为接口用例配置可读、可维护的结构化校验规则'">
      <template #actions><el-button @click="$router.back()">取消</el-button><el-button type="primary" :disabled="!item || !rules.length" @click="save">保存断言</el-button></template>
    </PageHeader>
    <el-alert v-if="!caseId" title="请从用例库选择一条用例后进入断言配置" type="info" show-icon :closable="false" />
    <div v-else class="assert-grid">
      <el-card shadow="never">
        <template #header><div class="card-head"><div><b>断言规则</b><p>选择真实响应字段、判断条件和期望值，无需编写 JSON。</p></div><el-button type="primary" plain @click="generateFromResponse" :disabled="!response">从响应生成断言</el-button></div></template>
        <StructuredAssertBuilder v-model="rules" :fields="responseFields" />
        <el-empty v-if="rules.length===0" description="暂无断言，可手动添加或从最近响应生成" :image-size="70" />
        <el-alert v-if="rules.some(r=>r.source==='$status'&&r.operator!=='eq')" class="rule-alert" type="warning" :closable="false" title="HTTP 状态码当前只支持“等于”判断，保存时会自动转换。" />
      </el-card>
      <el-card shadow="never">
        <template #header><div class="card-head"><div><b>最近响应样本</b><p>字段候选来自该接口最近一次真实执行。</p></div><el-button :disabled="!item?.endpoint_id" :loading="sampling" @click="sample">载入响应</el-button></div></template>
        <template v-if="response">
          <el-descriptions :column="2" border><el-descriptions-item label="状态码"><el-tag :type="response.status_code < 400 ? 'success' : 'danger'">{{ response.status_code }}</el-tag></el-descriptions-item><el-descriptions-item label="耗时">{{ response.elapsed_ms }} ms</el-descriptions-item><el-descriptions-item label="采集时间" :span="2">{{ response.captured_at }}</el-descriptions-item></el-descriptions>
          <div class="field-title">可用字段 <span>点击即可添加存在性断言</span></div>
          <div class="field-list"><button v-for="field in responseFields" :key="field" type="button" @click="addField(field)">{{field}}</button></div>
          <pre>{{ pretty(response.body) }}</pre>
        </template>
        <el-empty v-else description="执行过该接口后，可载入真实响应并自动生成断言"><el-button v-if="item?.endpoint_id" type="primary" plain :loading="sampling" @click="sample">获取最近响应</el-button></el-empty>
      </el-card>
    </div>
  </div>
</template>
<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { caseApi, endpointRuntimeApi } from '@/api'
import PageHeader from '@/components/PageHeader.vue'
import StructuredAssertBuilder, { type AssertRule } from '@/components/StructuredAssertBuilder.vue'

const route=useRoute(),caseId=String(route.params.id||route.query.case_id||'')
const item=ref<any>(null),loading=ref(false),sampling=ref(false),response=ref<any>(null),rules=ref<AssertRule[]>([])
function flatten(value:any,path='$.body',result:string[]=[]):string[]{if(result.length>=100)return result;if(value===null||typeof value!=='object'){result.push(path);return result}if(Array.isArray(value)){if(!value.length)result.push(path);else flatten(value[0],`${path}[0]`,result)}else{const keys=Object.keys(value);if(!keys.length)result.push(path);keys.forEach(k=>flatten(value[k],`${path}.${k}`,result))}return result}
const responseFields=computed(()=>response.value?flatten(response.value.body):[])
function pretty(v:any){return JSON.stringify(v,null,2)}
function fromStored(x:any):AssertRule{if(x.type==='status_code')return{source:'$status',operator:'eq',expected:x.expected};if(x.type==='response_time')return{source:'$elapsed',operator:'lt',expected:x.max_ms};if(x.type==='contains')return{source:'$.body',operator:'contains',expected:x.expected};return{source:`$.body${String(x.path||'$').replace(/^\$/,'')}`,operator:x.operator||'eq',expected:x.expected}}
async function load(){if(!caseId)return;loading.value=true;try{const r:any=await caseApi.get(caseId);item.value=r?.data;const expected=item.value?.expected_result||{};rules.value=(expected.assertions||[]).map(fromStored);if(expected.status_code&&!rules.value.some(x=>x.source==='$status'))rules.value.unshift({source:'$status',operator:'eq',expected:expected.status_code});if(item.value?.endpoint_id)await sample(false)}finally{loading.value=false}}
async function sample(showMessage=true){sampling.value=true;try{const r:any=await endpointRuntimeApi.lastResponse(item.value.endpoint_id);response.value=r?.data;if(!response.value&&showMessage)ElMessage.info('该接口暂无执行响应')}catch{response.value=null;if(showMessage)ElMessage.warning('暂无可用响应，请先运行一次该接口用例')}finally{sampling.value=false}}
function addField(field:string){if(!rules.value.some(r=>r.source===field))rules.value.push({source:field,operator:'exists'});else ElMessage.info('该字段已配置断言')}
function generateFromResponse(){const generated:AssertRule[]=[{source:'$status',operator:'eq',expected:response.value.status_code},...responseFields.value.slice(0,8).map(field=>({source:field,operator:'exists'} as AssertRule))];rules.value=generated;ElMessage.success(`已根据响应生成 ${generated.length} 条断言，请核对后保存`)}
function toStored(r:AssertRule):any{if(r.source==='$status')return{type:'status_code',expected:Number(r.expected)};if(r.source==='$elapsed')return{type:'response_time',max_ms:Number(r.expected)};const path=String(r.source).replace(/^\$\.body/,'$');if(r.source==='$.body'&&r.operator==='contains')return{type:'contains',expected:String(r.expected||'')};const row:any={type:'json_path',path,operator:r.operator};if(!['exists','not_exists'].includes(r.operator))row.expected=parseExpected(r.expected);return row}
function parseExpected(value:any){if(typeof value!=='string')return value;const v=value.trim();if(v==='true'||v==='false')return v==='true';if(v!==''&&!Number.isNaN(Number(v)))return Number(v);try{return JSON.parse(v)}catch{return value}}
async function save(){if(!rules.value.length){ElMessage.warning('至少配置一条断言');return}const normalized=rules.value.map(r=>toStored(r.source==='$status'?{...r,operator:'eq'}:r));const status=normalized.find(x=>x.type==='status_code');await caseApi.update(caseId,{expected_result:{status_code:status?.expected,assertions:normalized.filter(x=>x.type!=='status_code')}});ElMessage.success('断言已保存并形成新的用例版本')}
onMounted(load)
</script>
<style scoped>
.assert-page{display:grid;gap:16px}.assert-grid{display:grid;grid-template-columns:minmax(0,3fr) minmax(360px,2fr);gap:14px}.card-head{display:flex;justify-content:space-between;align-items:flex-start;gap:12px}.card-head p{margin:5px 0 0;color:var(--app-text-secondary);font-size:12px}.rule-alert{margin-top:14px}.field-title{margin:18px 0 8px;font-weight:600}.field-title span{font-weight:400;color:var(--app-text-secondary);font-size:12px}.field-list{display:flex;flex-wrap:wrap;gap:6px;max-height:120px;overflow:auto}.field-list button{border:1px solid var(--el-border-color);background:var(--el-fill-color-light);border-radius:5px;padding:5px 8px;color:var(--el-color-primary);cursor:pointer}pre{max-height:310px;overflow:auto;background:#0f172a;color:#dbeafe;border-radius:8px;padding:14px;font-size:12px}@media(max-width:980px){.assert-grid{grid-template-columns:1fr}}
</style>
