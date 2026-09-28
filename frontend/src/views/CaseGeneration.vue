<template>
  <div class="case-generation">
    <PageHeader title="用例设计中心" description="从需求、接口文档或人工设计创建用例，所有结果统一进入用例库评审。">
      <template #actions><el-button @click="goCaseLibrary">进入用例管理与评审</el-button></template>
    </PageHeader>

    <el-card shadow="never" class="source-card">
      <el-tabs v-model="activeSource" class="source-tabs">
        <el-tab-pane name="requirement"><template #label><span class="tab-label"><el-icon><Document /></el-icon>需求文档生成</span></template></el-tab-pane>
        <el-tab-pane name="interface"><template #label><span class="tab-label"><el-icon><Connection /></el-icon>接口文档生成</span></template></el-tab-pane>
        <el-tab-pane name="manual"><template #label><span class="tab-label"><el-icon><EditPen /></el-icon>手动添加 / 批量导入</span></template></el-tab-pane>
      </el-tabs>
      <p class="source-description">{{ sourceDescription }}</p>
    </el-card>

    <keep-alive v-if="activeSource !== 'manual'">
      <component :is="activeComponent" />
    </keep-alive>

    <template v-else>
      <el-card shadow="never">
        <div class="manual-head">
          <div><h3>人工创建用例</h3><p>少量用例可直接录入；已有资产可通过模板批量导入。</p></div>
          <el-select v-model="projectId" filterable placeholder="先选择项目" class="project-select"><el-option v-for="p in projects" :key="p.id" :label="p.name" :value="p.id" /></el-select>
        </div>
        <el-tabs v-model="manualMode">
          <el-tab-pane label="批量导入" name="import">
            <StepBar :items="importSteps" :active="importStage" />
            <div v-if="importStage === 0" class="stage-panel">
              <div><h3>下载标准模板</h3><p>模板包含 API 与手工用例所需字段，并附带一行示例数据。</p></div>
              <el-button type="primary" plain @click="downloadTemplate">下载 Excel 模板</el-button>
            </div>
            <div v-else-if="importStage === 1" class="stage-panel upload-panel">
              <el-upload drag :auto-upload="false" :show-file-list="false" accept=".csv,.json,.xlsx" :on-change="previewImport">
                <el-icon class="upload-icon"><UploadFilled /></el-icon><div>拖拽文件到这里，或点击选择文件</div><small>支持 CSV、JSON、XLSX，单次最多 2000 条</small>
              </el-upload>
            </div>
            <div v-else-if="importStage === 2" class="mapping-panel">
              <el-alert type="success" :closable="false" show-icon title="已自动识别模板字段，可在提交前核对映射结果。" />
              <el-table :data="mappingRows" border>
                <el-table-column prop="source" label="文件字段" />
                <el-table-column label="平台字段"><template #default="{ row }"><el-select v-model="row.target"><el-option v-for="field in targetFields" :key="field.value" :label="field.label" :value="field.value" /></el-select></template></el-table-column>
                <el-table-column prop="example" label="示例值" show-overflow-tooltip />
              </el-table>
            </div>
            <div v-else class="preview-panel">
              <el-alert :type="failedCount ? 'warning' : 'success'" :closable="false" show-icon :title="`校验通过 ${successCount} 条，错误 ${failedCount} 条；仅导入通过预检的数据。`" />
              <el-table :data="previewRows" max-height="420" border>
                <el-table-column prop="row_no" label="行" width="60" /><el-table-column label="用例名称" min-width="220"><template #default="{row}">{{row.data?.title}}</template></el-table-column>
                <el-table-column label="类型" width="110"><template #default="{row}">{{row.data?.execution_kind === 'manual' ? '手工' : 'API'}}</template></el-table-column>
                <el-table-column label="校验" min-width="260"><template #default="{row}"><el-tag :type="row.valid?'success':'danger'">{{row.valid?'通过':'错误'}}</el-tag><span class="row-error">{{(row.errors||[]).join('；')}}</span></template></el-table-column>
              </el-table>
            </div>
            <div class="stage-actions">
              <el-button v-if="importStage > 0" @click="importStage--">上一步</el-button>
              <el-button v-if="importStage === 0" type="primary" :disabled="!projectId" @click="importStage = 1">下一步：上传文件</el-button>
              <el-button v-else-if="importStage === 2" type="primary" @click="importStage = 3">下一步：预览校验</el-button>
              <el-button v-else-if="importStage === 3" type="primary" :loading="importing" :disabled="!successCount" @click="commitImport">导入 {{ successCount }} 条</el-button>
            </div>
          </el-tab-pane>

          <el-tab-pane label="逐条录入" name="single">
            <el-form label-position="top" class="manual-form">
              <div class="form-grid"><el-form-item label="用例名称" required><el-input v-model="form.title" placeholder="描述要验证的业务行为" /></el-form-item><el-form-item label="优先级"><el-select v-model="form.priority"><el-option v-for="p in ['P0','P1','P2','P3']" :key="p" :label="p" :value="p" /></el-select></el-form-item><el-form-item label="业务目录"><el-input v-model="form.folder" placeholder="例如：订单 / 支付" /></el-form-item><el-form-item label="标签"><el-select v-model="form.tags" multiple filterable allow-create default-first-option /></el-form-item></div>
              <el-form-item label="前置条件"><el-input v-model="form.description" type="textarea" :rows="2" placeholder="执行前需要满足的条件" /></el-form-item>
              <div class="section-head"><b>执行步骤</b><el-button link type="primary" @click="form.steps.push('')">添加步骤</el-button></div>
              <div v-for="(_, index) in form.steps" :key="index" class="step-row"><span>{{ index + 1 }}</span><el-input v-model="form.steps[index]" :placeholder="`第 ${index + 1} 步操作`" /><el-button text type="danger" aria-label="删除步骤" @click="form.steps.splice(index, 1)">删除</el-button></div>
              <el-form-item label="预期结果" required><el-input v-model="form.expected" type="textarea" :rows="3" placeholder="明确、可验证的预期结果" /></el-form-item>
              <div class="form-actions"><el-button @click="resetForm">重置</el-button><el-button type="primary" :loading="saving" :disabled="!projectId" @click="saveManualCase">保存为草稿</el-button></div>
            </el-form>
          </el-tab-pane>
        </el-tabs>
      </el-card>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Connection, Document, EditPen, UploadFilled } from '@element-plus/icons-vue'
import { ElMessage, type UploadFile } from 'element-plus'
import RequirementParse from '@/views/RequirementParse.vue'
import DocParser from '@/views/DocParser.vue'
import PageHeader from '@/components/PageHeader.vue'
import StepBar from '@/components/StepBar.vue'
import { caseApi, projectApi } from '@/api'

type Source = 'requirement' | 'interface' | 'manual'
const route = useRoute(), router = useRouter()
const projects = ref<any[]>([]), projectId = ref(String(route.query.project_id || ''))
const manualMode = ref('import'), importStage = ref(0), previewRows = ref<any[]>([])
const successCount = ref(0), failedCount = ref(0), importing = ref(false), saving = ref(false)
const importSteps = ['下载模板', '上传文件', '字段映射', '预览并导入']
const targetFields = [{label:'用例名称',value:'title'},{label:'描述',value:'description'},{label:'执行类型',value:'execution_kind'},{label:'设计类型',value:'case_type'},{label:'优先级',value:'priority'},{label:'目录',value:'folder'},{label:'标签',value:'tags'},{label:'请求方法',value:'method'},{label:'请求地址',value:'url'},{label:'预期结果',value:'expected_result'}]
const mappingRows = ref<any[]>([])
const form = reactive({ title:'', description:'', priority:'P2', folder:'', tags:[] as string[], steps:[''], expected:'' })
const activeSource = computed<Source>({ get:()=>['interface','manual'].includes(String(route.query.source)) ? route.query.source as Source : 'requirement', set:(source)=>router.replace({path:'/case-generation',query:{...route.query,source}}) })
const activeComponent = computed(()=>activeSource.value==='interface'?DocParser:RequirementParse)
const sourceDescription = computed(()=>activeSource.value==='requirement'?'上传 PRD 或验收标准，解析需求并生成可追溯的功能用例草稿。':activeSource.value==='interface'?'导入 OpenAPI、Swagger 或 HAR，建立接口资产并生成可执行的 API 用例。':'直接录入少量用例，或使用模板批量迁移企业现有测试资产。')

async function loadProjects(){const r:any=await projectApi.getList();projects.value=Array.isArray(r?.data)?r.data:(r?.data?.items||r?.data?.list||[]);if(!projectId.value)projectId.value=projects.value[0]?.id||''}
function goCaseLibrary(){router.push({path:'/case-library',query:projectId.value?{project_id:projectId.value}:{}})}
async function downloadTemplate(){const r:any=await caseApi.importTemplate();const url=URL.createObjectURL(r.data);const a=document.createElement('a');a.href=url;a.download='用例导入模板.xlsx';a.click();URL.revokeObjectURL(url)}
async function previewImport(file:UploadFile){if(!projectId.value){ElMessage.warning('请先选择项目');return}if(!file.raw)return;try{const r:any=await caseApi.importPreview(projectId.value,file.raw);const data=r?.data||{};previewRows.value=data.rows||[];successCount.value=data.success_count||0;failedCount.value=data.failed_count||0;const sample=previewRows.value[0]?.data||{};mappingRows.value=targetFields.map(x=>({source:x.label,target:x.value,example:typeof sample[x.value]==='object'?JSON.stringify(sample[x.value]):String(sample[x.value]??'—')}));importStage.value=2}catch(e:any){ElMessage.error(e?.message||'文件解析失败')}}
async function commitImport(){importing.value=true;try{await caseApi.importCommit({project_id:projectId.value,rows:previewRows.value.filter(x=>x.valid).map(x=>x.data)});ElMessage.success(`已导入 ${successCount.value} 条用例草稿`);goCaseLibrary()}finally{importing.value=false}}
function resetForm(){Object.assign(form,{title:'',description:'',priority:'P2',folder:'',tags:[],steps:[''],expected:''})}
async function saveManualCase(){if(!form.title.trim()||!form.expected.trim()){ElMessage.warning('请填写用例名称和预期结果');return}saving.value=true;try{await caseApi.importCommit({project_id:projectId.value,rows:[{title:form.title.trim(),description:form.description,execution_kind:'manual',case_type:'functional',priority:form.priority,folder:form.folder,tags:form.tags,request_data:{steps:form.steps.filter(Boolean)},expected_result:{text:form.expected.trim()}}]});ElMessage.success('用例草稿已保存');resetForm();goCaseLibrary()}finally{saving.value=false}}
onMounted(loadProjects)
</script>

<style scoped>
.case-generation{display:grid;gap:16px}.source-card{padding-bottom:2px}.source-tabs :deep(.el-tabs__content){display:none}.tab-label{display:inline-flex;align-items:center;gap:7px;padding:0 8px;font-weight:600}.source-description,.manual-head p,.stage-panel p{margin:4px 0 0;color:var(--app-text-secondary);font-size:13px}.manual-head,.stage-panel,.stage-actions,.section-head,.form-actions{display:flex;justify-content:space-between;align-items:center;gap:16px}.manual-head h3,.stage-panel h3{margin:0}.project-select{width:260px}.stage-panel,.mapping-panel,.preview-panel{margin:18px 0;padding:24px;border:1px solid var(--el-border-color-light);border-radius:10px;background:var(--el-fill-color-lighter)}.upload-panel{display:block}.upload-icon{font-size:38px;color:var(--el-color-primary)}.mapping-panel,.preview-panel{display:grid;gap:14px}.row-error{margin-left:8px;color:var(--el-color-danger)}.manual-form{max-width:980px;padding:14px 2px}.form-grid{display:grid;grid-template-columns:2fr 1fr 1fr 1.5fr;gap:12px}.step-row{display:grid;grid-template-columns:28px 1fr 60px;gap:8px;align-items:center;margin:10px 0}.form-actions{justify-content:flex-end}@media(max-width:860px){.manual-head,.stage-panel{align-items:flex-start;flex-direction:column}.project-select{width:100%}.form-grid{grid-template-columns:1fr 1fr}}@media(max-width:560px){.form-grid{grid-template-columns:1fr}}
</style>
