<template>
  <div class="dashboard">
    <PageHeader title="工作台" description="查看需要处理的测试工作、项目状态与最近质量变化。"><template #actions><el-button type="primary" @click="$router.push('/case-generation')">生成测试用例</el-button></template></PageHeader>
    <div class="stat-grid"><el-card v-for="card in statCards" :key="card.title" shadow="never" class="stat-card" @click="goStat(card.title)"><span>{{card.title}}</span><strong>{{card.value}}</strong><small>{{card.tip}}</small></el-card></div>
    <div class="main-grid">
      <el-card shadow="never"><template #header><div class="card-head"><div><b>我的待办</b><p>由评审、环境和失败运行实时聚合</p></div></div></template><button v-for="item in todos" :key="item.id" type="button" class="todo" @click="$router.push(item.path)"><span class="todo-dot" :class="item.priority"/><span><b>{{item.title}}</b><small>{{item.description}}</small></span><el-icon><ArrowRight/></el-icon></button><el-empty v-if="!todos.length" description="当前没有待办，所有关键流程均已就绪" :image-size="60"/></el-card>
      <el-card shadow="never"><template #header><div class="card-head"><div><b>通过率趋势</b><p>按已完成运行的门禁结果计算</p></div><el-select v-model="days" size="small" @change="loadTrend"><el-option label="近 7 天" :value="7"/><el-option label="近 30 天" :value="30"/><el-option label="近 90 天" :value="90"/></el-select></div></template><el-alert v-if="trendError" :title="trendError" type="error" :closable="false"><el-button link @click="loadTrend">重试</el-button></el-alert><TrendChart v-else-if="trend.dates.length" :labels="trend.dates" :series="[{name:'通过率',data:trend.pass_rates,color:CHART_COLORS.success}]" :height="245" y-axis-name="%"/><el-empty v-else description="暂无趋势，完成一次测试后自动生成" :image-size="60"/></el-card>
    </div>
    <el-card shadow="never"><template #header><div class="card-head"><div><b>我的项目</b><p>用例规模、最近执行与环境就绪状态</p></div><el-button text type="primary" @click="$router.push('/projects')">全部项目</el-button></div></template><el-table :data="projectRows" @row-click="openProject"><el-table-column prop="name" label="项目" min-width="180"><template #default="{row}"><b class="link">{{row.name}}</b></template></el-table-column><el-table-column prop="case_count" label="用例数" width="100"/><el-table-column label="最近执行" min-width="160"><template #default="{row}">{{row.recent_run_at?formatTime(row.recent_run_at):'尚未执行'}}</template></el-table-column><el-table-column label="质量分" width="100"><template #default="{row}">{{row.quality_score??'—'}}</template></el-table-column><el-table-column label="状态" width="130"><template #default="{row}"><el-tag :type="row.ready?'success':'warning'">{{row.ready?'已就绪':'待配置环境'}}</el-tag></template></el-table-column></el-table><el-empty v-if="!projectRows.length" description="暂无项目"><el-button type="primary" @click="$router.push('/projects')">创建项目</el-button></el-empty></el-card>
    <el-card shadow="never"><template #header><div class="card-head"><div><b>最近执行</b><p>点击运行编号查看完整执行时间线</p></div><el-button text type="primary" @click="$router.push('/runs')">全部执行</el-button></div></template><el-alert v-if="runsError" :title="runsError" type="error" :closable="false"><el-button link @click="loadRuns">重试</el-button></el-alert><el-table v-else :data="recentRuns" v-loading="loading"><el-table-column label="运行编号" width="145"><template #default="{row}"><el-link type="primary" @click="$router.push(`/runs/${row.id}`)">RUN-{{row.id.slice(0,8)}}</el-link></template></el-table-column><el-table-column prop="project_name" label="项目" min-width="150"/><el-table-column label="状态" width="110"><template #default="{row}"><StatusPill :status="row.status" :map="RUN_STATUS"/></template></el-table-column><el-table-column label="质量分" width="90"><template #default="{row}">{{row.quality_score??'—'}}</template></el-table-column><el-table-column label="触发时间" min-width="170"><template #default="{row}">{{formatTime(row.created_at)}}</template></el-table-column></el-table><el-pagination v-if="runsTotal>pageSize" v-model:current-page="page" :total="runsTotal" :page-size="pageSize" layout="prev,pager,next,total" @current-change="loadRuns"/></el-card>
  </div>
</template>
<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ArrowRight } from '@element-plus/icons-vue'
import dayjs from 'dayjs'
import { dashboardApi, trendApi } from '@/api'
import { CHART_COLORS } from '@/styles/chartPalette'
import { RUN_STATUS } from '@/constants/status'
import PageHeader from '@/components/PageHeader.vue'
import StatusPill from '@/components/StatusPill.vue'
import TrendChart from '@/components/TrendChart.vue'
const router=useRouter(),days=ref(30),loading=ref(false),page=ref(1),pageSize=5,runsTotal=ref(0)
const todos=ref<any[]>([]),projectRows=ref<any[]>([]),recentRuns=ref<any[]>([]),runsError=ref(''),trendError=ref('')
const trend=ref({dates:[] as string[],pass_rates:[] as number[]})
const statCards=ref([{title:'测试任务总数',value:0,tip:'当前统计周期'},{title:'通过率',value:'0%',tip:'门禁通过运行'},{title:'发现缺陷',value:0,tip:'当前统计周期'},{title:'平均质量分',value:'0',tip:'最近报告均值'}])
function formatTime(t:string){return t?dayjs(t).format('YYYY-MM-DD HH:mm'):'—'}
function goStat(title:string){router.push(title==='发现缺陷'?'/defects':title==='测试任务总数'?'/runs':'/quality-trend')}
function openProject(row:any){router.push(`/projects/${row.id}/overview`)}
async function loadStats(){const r:any=await dashboardApi.getStatistics(days.value);const d=r?.data||{};statCards.value[0].value=d.total_runs||0;statCards.value[1].value=`${d.pass_rate||0}%`;statCards.value[2].value=d.total_defects||0;statCards.value[3].value=Number(d.avg_quality_score||0).toFixed(1)}
async function loadTrend(){trendError.value='';try{const r:any=await trendApi.getPassRate({days:days.value});trend.value=r?.data||{dates:[],pass_rates:[]};await loadStats()}catch(e:any){trendError.value=e?.message||'趋势加载失败'}}
async function loadRuns(){runsError.value='';loading.value=true;try{const r:any=await dashboardApi.getRecentRuns(pageSize,page.value);recentRuns.value=r?.data?.list||[];runsTotal.value=r?.data?.total||0}catch(e:any){runsError.value=e?.message||'最近执行加载失败'}finally{loading.value=false}}
async function loadBase(){const [t,p]=await Promise.all([dashboardApi.getTodos(),dashboardApi.getProjectsSummary(6)]) as any[];todos.value=t?.data?.items||[];projectRows.value=p?.data?.items||[]}
onMounted(()=>Promise.all([loadBase(),loadTrend(),loadRuns()]))
</script>
<style scoped>
.dashboard{display:grid;gap:16px}.stat-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}.stat-card{cursor:pointer}.stat-card :deep(.el-card__body){display:grid;gap:6px}.stat-card span,.stat-card small,.card-head p{color:var(--app-text-secondary);font-size:12px}.stat-card strong{font-size:26px}.main-grid{display:grid;grid-template-columns:minmax(320px,1fr) minmax(0,1.6fr);gap:16px}.card-head{display:flex;align-items:flex-start;justify-content:space-between;gap:12px}.card-head p{margin:5px 0 0}.card-head .el-select{width:110px}.todo{width:100%;display:grid;grid-template-columns:10px 1fr 20px;gap:10px;align-items:center;padding:12px 4px;border:0;border-bottom:1px solid var(--el-border-color-lighter);background:none;text-align:left;cursor:pointer}.todo span:nth-child(2){display:grid;gap:4px}.todo small{color:var(--app-text-secondary)}.todo-dot{width:8px;height:8px;border-radius:50%;background:var(--el-color-info)}.todo-dot.high{background:var(--el-color-danger)}.todo-dot.medium{background:var(--el-color-warning)}.link{color:var(--el-color-primary)}.el-pagination{justify-content:flex-end;margin-top:14px}@media(max-width:960px){.stat-grid{grid-template-columns:1fr 1fr}.main-grid{grid-template-columns:1fr}}@media(max-width:560px){.stat-grid{grid-template-columns:1fr}}
</style>
