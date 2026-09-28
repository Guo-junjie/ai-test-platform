<template>
  <div class="app-page">
    <div class="app-page-head"><div><h1>执行记录</h1><p>集中查看手动、定时和 CI 触发的测试运行及执行证据。</p></div><el-button :loading="loading" @click="load"><el-icon><Refresh /></el-icon>刷新</el-button></div>
    <el-card shadow="never" class="filter-card">
      <el-form inline><el-form-item label="项目"><el-select v-model="filters.project_id" clearable filterable placeholder="全部项目" style="width:220px" @change="load"><el-option v-for="p in projects" :key="p.id" :label="p.name" :value="p.id" /></el-select></el-form-item><el-form-item label="状态"><el-select v-model="filters.status" clearable placeholder="全部状态" style="width:150px" @change="load"><el-option v-for="s in statuses" :key="s.value" :label="s.label" :value="s.value" /></el-select></el-form-item><el-form-item><el-input v-model="filters.keyword" clearable placeholder="运行 ID / 分支" @keyup.enter="load" /></el-form-item></el-form>
    </el-card>
    <el-card shadow="never" class="table-card">
      <el-table v-loading="loading" :data="runs" row-key="id" @row-click="openRun">
        <el-table-column label="运行" min-width="210"><template #default="{row}"><div class="run-name">{{ row.name || row.source_ref || '自动化测试运行' }}</div><code>{{ row.id }}</code></template></el-table-column>
        <el-table-column label="状态" width="110"><template #default="{row}"><el-tag :type="statusType(row.status)" effect="light">{{ statusLabel(row.status) }}</el-tag></template></el-table-column>
        <el-table-column label="触发方式" width="120"><template #default="{row}">{{ triggerLabel(row.trigger_type) }}</template></el-table-column>
        <el-table-column label="进度" width="160"><template #default="{row}"><el-progress :percentage="row.progress || (row.status === 'completed' ? 100 : 0)" :stroke-width="7" /></template></el-table-column>
        <el-table-column prop="source_ref" label="分支/版本" min-width="150" show-overflow-tooltip />
        <el-table-column label="开始时间" width="175"><template #default="{row}">{{ formatTime(row.created_at) }}</template></el-table-column>
        <el-table-column label="操作" width="90" fixed="right"><template #default="{row}"><el-button link type="primary" @click.stop="openRun(row)">查看详情</el-button></template></el-table-column>
      </el-table>
      <el-empty v-if="!loading && runs.length === 0" description="暂无符合条件的执行记录" />
      <el-pagination v-if="total > pageSize" v-model:current-page="page" :page-size="pageSize" :total="total" layout="prev, pager, next, total" @current-change="load" />
    </el-card>
  </div>
</template>
<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'; import { useRouter } from 'vue-router'; import { Refresh } from '@element-plus/icons-vue'; import { projectApi, testRunApi } from '@/api'
const router=useRouter(); const loading=ref(false), runs=ref<any[]>([]), projects=ref<any[]>([]), total=ref(0), page=ref(1); const pageSize=20
const filters=reactive({project_id:'',status:'',keyword:''}); const statuses=[{value:'pending',label:'等待中'},{value:'executing',label:'执行中'},{value:'completed',label:'已完成'},{value:'failed',label:'失败'},{value:'cancelled',label:'已取消'}]
const labels:any={pending:'等待中',pulling:'拉取代码',analyzing:'解析代码',generating:'生成用例',executing:'执行中',analyzing_defects:'分析缺陷',reporting:'生成报告',completed:'已完成',failed:'失败',cancelled:'已取消'}
function statusLabel(v:string){return labels[v]||v||'未知'} function statusType(v:string){return v==='completed'?'success':v==='failed'?'danger':v==='cancelled'?'info':'warning'} function triggerLabel(v:string){return ({manual:'手动',schedule:'定时任务',webhook:'CI / Webhook',retry:'重试'} as any)[v]||'手动'}
function formatTime(v:string){return v?new Date(v).toLocaleString('zh-CN'):'—'} function openRun(row:any){router.push(`/runs/${row.id}`)}
async function load(){loading.value=true;try{const r:any=await testRunApi.getList({...filters,page:page.value,page_size:pageSize});const data=r?.data||{};runs.value=data.list||data.items||[];total.value=data.total??runs.value.length}catch{runs.value=[];total.value=0}finally{loading.value=false}}
onMounted(async()=>{try{const r:any=await projectApi.getList({page_size:200});projects.value=r?.data?.items||r?.data?.list||r?.data||[]}catch{projects.value=[]}await load()})
</script>
<style scoped>.app-page-head{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:18px}.app-page-head h1{margin:0 0 6px;font-size:22px}.app-page-head p{margin:0;color:var(--app-text-secondary)}.filter-card{margin-bottom:14px}.filter-card :deep(.el-form-item){margin-bottom:0}.table-card :deep(.el-table__row){cursor:pointer}.run-name{font-weight:600;color:var(--app-text-primary);margin-bottom:3px}.run-name+code{font-size:11px;color:var(--app-text-placeholder)}.el-pagination{justify-content:flex-end;margin-top:16px}@media(max-width:768px){.app-page-head{gap:12px}.filter-card :deep(.el-form){display:grid}.filter-card :deep(.el-select),.filter-card :deep(.el-input){width:100%!important}}</style>
