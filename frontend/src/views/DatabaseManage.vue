<template>
  <div class="database-manage-page">
    <el-card shadow="hover">
      <template #header>
        <div class="card-header">
          <span>数据库连接管理</span>
          <el-button type="primary" @click="openCreateDialog">
            <el-icon><Plus /></el-icon>
            新建连接
          </el-button>
        </div>
      </template>

      <div class="filter-bar" style="margin-bottom: 16px;">
        <el-select v-model="projectId" placeholder="选择项目" filterable style="width: 300px;" @change="loadDatabases">
          <el-option v-for="p in projects" :key="p.id" :label="p.name" :value="p.id" />
        </el-select>
      </div>

      <el-table :data="databases" v-loading="loading" style="width: 100%">
        <el-table-column prop="name" label="名称" />
        <el-table-column prop="db_type" label="类型" width="120" />
        <el-table-column prop="host" label="主机" />
        <el-table-column prop="port" label="端口" width="80" />
        <el-table-column prop="database" label="库名" />
        <el-table-column prop="username" label="用户名" width="120" />
        <el-table-column label="操作" width="260">
          <template #default="{ row }">
            <el-button size="small" type="primary" plain @click="viewSchema(row)">查看表结构</el-button>
            <el-button size="small" plain @click="openEditDialog(row)">编辑</el-button>
            <el-button size="small" type="danger" plain @click="handleDelete(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 新建/编辑对话框 -->
    <el-dialog
      v-model="dialogVisible"
      :title="isEdit ? '编辑数据库连接' : '新建数据库连接'"
      width="560px"
      destroy-on-close
    >
      <el-form ref="formRef" :model="form" :rules="formRules" label-width="110px">
        <el-form-item label="连接名称" prop="name">
          <el-input v-model="form.name" placeholder="例如：生产环境数据库" />
        </el-form-item>
        <el-form-item label="数据库类型" prop="db_type">
          <el-select v-model="form.db_type" style="width: 100%;">
            <el-option label="PostgreSQL" value="postgresql" />
            <el-option label="MySQL" value="mysql" />
          </el-select>
        </el-form-item>
        <el-form-item label="主机地址" prop="host">
          <el-input v-model="form.host" placeholder="例如：127.0.0.1" />
        </el-form-item>
        <el-form-item label="端口" prop="port">
          <el-input-number v-model="form.port" :min="1" :max="65535" />
        </el-form-item>
        <el-form-item label="数据库名" prop="database">
          <el-input v-model="form.database" placeholder="数据库名称" />
        </el-form-item>
        <el-form-item label="用户名" prop="username">
          <el-input v-model="form.username" />
        </el-form-item>
        <el-form-item label="密码" prop="password">
          <el-input
            v-model="form.password"
            type="password"
            show-password
            :placeholder="isEdit ? '留空表示不修改' : '输入密码'"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submitForm">确定</el-button>
      </template>
    </el-dialog>

    <!-- 表结构对话框 -->
    <el-dialog v-model="schemaVisible" title="表结构" width="720px">
      <div v-loading="schemaLoading">
        <el-collapse v-if="schemaData && schemaData.tables?.length">
          <el-collapse-item
            v-for="table in schemaData.tables"
            :key="table.name"
            :title="`${table.name} (${table.columns?.length || 0} 列)`"
          >
            <el-table :data="table.columns" size="small" border>
              <el-table-column prop="name" label="列名" />
              <el-table-column prop="type" label="类型" />
              <el-table-column label="可空" width="80">
                <template #default="{ row }">
                  {{ row.nullable ? '是' : '否' }}
                </template>
              </el-table-column>
              <el-table-column prop="default" label="默认值" />
            </el-table>
          </el-collapse-item>
        </el-collapse>
        <el-empty v-else-if="!schemaLoading" description="未查询到表结构" />
      </div>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from 'element-plus'
import { databaseApi, projectApi } from '@/api'

const projectId = ref('')
const projects = ref<any[]>([])
const databases = ref<any[]>([])
const loading = ref(false)
const submitting = ref(false)

const dialogVisible = ref(false)
const isEdit = ref(false)
const currentId = ref('')
const formRef = ref<FormInstance>()

const schemaVisible = ref(false)
const schemaLoading = ref(false)
const schemaData = ref<any>(null)

const form = reactive({
  name: '',
  db_type: 'postgresql',
  host: '',
  port: 5432,
  database: '',
  username: '',
  password: '',
})

const formRules: FormRules = {
  name: [{ required: true, message: '请输入连接名称', trigger: 'blur' }],
  host: [{ required: true, message: '请输入主机地址', trigger: 'blur' }],
  port: [{ required: true, message: '请输入端口', trigger: 'blur' }],
  database: [{ required: true, message: '请输入数据库名', trigger: 'blur' }],
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
}

async function loadProjects(): Promise<void> {
  try {
    const res: any = await projectApi.getList()
    projects.value = Array.isArray(res?.data) ? res.data : (res?.data?.items || res?.data?.list || [])
  } catch {
    projects.value = []
  }
}

async function loadDatabases(): Promise<void> {
  if (!projectId.value) {
    databases.value = []
    return
  }
  loading.value = true
  try {
    const res: any = await databaseApi.listDatabases(projectId.value)
    databases.value = Array.isArray(res?.data) ? res.data : (res?.data?.items || res?.data?.list || [])
  } catch {
    databases.value = []
  } finally {
    loading.value = false
  }
}

function openCreateDialog(): void {
  if (!projectId.value) {
    ElMessage.warning('请先选择项目')
    return
  }
  isEdit.value = false
  currentId.value = ''
  Object.assign(form, {
    name: '', db_type: 'postgresql', host: '', port: 5432,
    database: '', username: '', password: '',
  })
  dialogVisible.value = true
}

function openEditDialog(row: any): void {
  isEdit.value = true
  currentId.value = row.id
  Object.assign(form, {
    name: row.name, db_type: row.db_type, host: row.host, port: row.port,
    database: row.database, username: row.username, password: '',
  })
  dialogVisible.value = true
}

async function submitForm(): Promise<void> {
  if (!formRef.value) return
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return

  submitting.value = true
  try {
    const payload: Record<string, any> = {
      name: form.name,
      db_type: form.db_type,
      host: form.host,
      port: form.port,
      database: form.database,
      username: form.username,
    }
    if (isEdit.value) {
      if (form.password) payload.password = form.password
      await databaseApi.updateDatabase(currentId.value, payload)
      ElMessage.success('更新成功')
    } else {
      payload.password = form.password
      payload.project_id = projectId.value
      await databaseApi.createDatabase(payload)
      ElMessage.success('创建成功')
    }
    dialogVisible.value = false
    await loadDatabases()
  } catch (e: any) {
    ElMessage.error(e?.message || '保存失败')
  } finally {
    submitting.value = false
  }
}

async function handleDelete(row: any): Promise<void> {
  try {
    await ElMessageBox.confirm(
      `确认删除数据库连接「${row.name}」吗？`,
      '删除确认',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }
    )
  } catch {
    return
  }
  try {
    await databaseApi.deleteDatabase(row.id)
    ElMessage.success('删除成功')
    await loadDatabases()
  } catch (e: any) {
    ElMessage.error(e?.message || '删除失败')
  }
}

async function viewSchema(row: any): Promise<void> {
  schemaVisible.value = true
  schemaLoading.value = true
  schemaData.value = null
  try {
    const res: any = await databaseApi.getSchema(row.id)
    schemaData.value = res?.data ?? res
  } catch (e: any) {
    ElMessage.error(e?.message || '获取表结构失败')
  } finally {
    schemaLoading.value = false
  }
}

onMounted(() => {
  loadProjects()
})
</script>

<style scoped>
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
</style>
