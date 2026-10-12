<template>
  <div class="case-library">
    <el-card shadow="hover" class="library-header">
      <div class="header-row">
        <div>
          <h2>用例管理与评审</h2>
          <p>统一管理需求、接口文档、文件导入与人工设计产生的测试资产</p>
        </div>
        <div class="project-picker">
          <span>项目</span>
          <el-select v-model="projectId" placeholder="选择项目" filterable @change="onProjectChange">
            <el-option v-for="project in projects" :key="project.id" :label="project.name" :value="project.id" />
          </el-select>
          <el-button v-if="canCreateCase" type="primary" :icon="Plus" :disabled="!projectId" @click="createVisible = true">新建用例</el-button>
          <el-button v-if="canCreateCase" :icon="Upload" :disabled="!projectId" @click="importVisible = true">批量导入</el-button>
          <el-button :icon="MagicStick" :disabled="!projectId" @click="goCaseGeneration">智能生成</el-button>
          <el-button :loading="listLoading" @click="loadCases">刷新</el-button>
        </div>
      </div>
    </el-card>

    <el-card shadow="hover" class="library-card" v-loading="listLoading">
      <el-tabs v-model="libraryTab" class="library-tabs" @tab-change="onLibraryTabChange">
        <el-tab-pane label="全部用例" name="all" />
        <el-tab-pane label="待我评审" name="review" />
        <el-tab-pane label="已归档" name="archived" />
      </el-tabs>
      <div class="filter-row">
        <el-input
          v-model="searchKeyword"
          placeholder="搜索标题或描述"
          clearable
          class="keyword-input"
          @keyup.enter="onFilterChange"
          @clear="onFilterChange"
        >
          <template #append>
            <el-button icon="Search" aria-label="搜索测试用例" @click="onFilterChange" />
          </template>
        </el-input>
        <el-select v-model="activeSource" clearable placeholder="全部来源" style="width: 150px" @change="onFilterChange">
          <el-option label="需求生成" value="requirement" />
          <el-option label="AI 接口生成" value="ai_generated" />
          <el-option label="人工创建" value="manual" />
        </el-select>
        <el-select v-model="activeType" placeholder="全部设计类型" style="width: 150px" @change="onFilterChange">
          <el-option label="全部类型" value="all" />
          <el-option label="需求/功能" value="functional" />
          <el-option label="正向" value="positive" />
          <el-option label="反向" value="negative" />
          <el-option label="边界" value="boundary" />
          <el-option label="异常" value="exception" />
        </el-select>
        <span class="result-count">{{ totalCases }} 条用例</span>
      </div>

      <div v-if="selectedRows.length" class="batch-toolbar">
        <strong>已选择 {{ selectedRows.length }} 条</strong>
        <el-button v-if="libraryTab === 'review'" size="small" :loading="batchAdopting" @click="batchAdopt">批量提交通过结论</el-button>
        <el-button v-if="libraryTab !== 'review'" size="small" @click="openBatchFolder">批量归类</el-button>
        <el-button v-if="libraryTab !== 'review'" size="small" @click="openBatchTags">批量添加标签</el-button>
        <el-button
          v-if="libraryTab !== 'review'"
          size="small"
          type="primary"
          plain
          :disabled="selectedRows.some((row: any) => row.status !== 'adopted' || row.execution_kind === 'manual')"
          @click="openAddToPlan(selectedRows.map((row: any) => row.id))"
        >
          批量加入计划
        </el-button>
      </div>

      <div ref="caseTableContainer">
      <el-table ref="caseTable" :data="cases" row-key="id" stripe :row-class-name="caseRowClass" @selection-change="onSelectionChange">
        <el-table-column type="selection" width="46" />
        <el-table-column label="用例" min-width="280">
          <template #default="{ row }">
            <button class="case-title" type="button" @click="openDetail(row)">{{ row.title }}</button>
            <el-tag v-if="row.id === highlightedCaseId" size="small" type="success" class="new-case-tag">新添加</el-tag>
            <div class="case-description">{{ row.description || '暂无描述' }}</div>
            <div class="case-meta">
              <el-tag v-if="row.folder" size="small" effect="plain">{{ row.folder }}</el-tag>
              <el-tag v-for="tag in (row.tags || []).slice(0, 3)" :key="tag" size="small" type="info" effect="plain">{{ tag }}</el-tag>
              <span v-if="(row.tags || []).length > 3">+{{ row.tags.length - 3 }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="请求" min-width="240">
          <template #default="{ row }">
            <template v-if="row.execution_kind !== 'manual'">
              <span class="method-tag" :class="`method-${String(row.request_data?.method || 'get').toLowerCase()}`">
                {{ row.request_data?.method || 'GET' }}
              </span>
              <span class="url-text">{{ row.request_data?.url || '未配置路径' }}</span>
            </template>
            <span v-else class="manual-label">手工用例 · {{ row.request_data?.steps?.length || 0 }} 个步骤</span>
          </template>
        </el-table-column>
        <el-table-column label="来源" width="120" align="center">
          <template #default="{ row }">
            <el-tag size="small" :type="sourceType(row.source)" effect="plain">{{ sourceLabel(row.source) }}</el-tag>
            <div class="version-label">v{{ row.version || 1 }}</div>
          </template>
        </el-table-column>
        <el-table-column label="优先级" width="82" align="center">
          <template #default="{ row }"><el-tag size="small" :type="priorityType(row.priority)">{{ row.priority }}</el-tag></template>
        </el-table-column>
        <el-table-column label="状态" width="100" align="center">
          <template #default="{ row }">
            <el-tag size="small" :type="reviewTagType(row)">{{ reviewLabel(row) }}</el-tag>
            <div v-if="row.review_task" class="version-label">{{ row.review_task.approved_count }}/{{ row.review_task.reviewer_count }} 已通过</div>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="250" fixed="right" align="center">
          <template #default="{ row }">
            <el-button size="small" text type="primary" @click="openDetail(row)">查看</el-button>
            <template v-if="libraryTab === 'review'">
              <el-button size="small" text type="primary" @click="openReviewTask(row)">评审</el-button>
            </template>
            <el-button v-else-if="libraryTab === 'archived'" size="small" text type="success" @click="restoreCase(row)">恢复</el-button>
            <el-button
              v-else
              size="small"
              text
              type="success"
              :disabled="row.status !== 'adopted'"
              @click="row.execution_kind === 'manual' ? openManualExecution(row) : openRun(row)"
            >{{ row.execution_kind === 'manual' ? '执行' : '运行' }}</el-button>
            <el-dropdown trigger="click" @command="handleMore($event, row)">
              <el-button size="small" text>更多<el-icon class="el-icon--right"><MoreFilled /></el-icon></el-button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="edit">编辑</el-dropdown-item>
                  <el-dropdown-item command="assert" :disabled="row.execution_kind === 'manual'">配置断言</el-dropdown-item>
                  <el-dropdown-item command="copy">复制</el-dropdown-item>
                  <el-dropdown-item command="review-tasks">评审任务</el-dropdown-item>
                  <el-dropdown-item command="review-events">评审记录</el-dropdown-item>
                  <el-dropdown-item command="submit" :disabled="!['draft', 'changes_requested'].includes(row.review_state)">提交评审</el-dropdown-item>
                  <el-dropdown-item command="approve" :disabled="row.review_state !== 'pending'">进入评审</el-dropdown-item>
                  <el-dropdown-item command="plan" :disabled="row.status !== 'adopted' || row.execution_kind === 'manual'">加入计划</el-dropdown-item>
                  <el-dropdown-item divided command="deprecate" :disabled="row.status === 'deprecated'">废弃</el-dropdown-item>
                  <el-dropdown-item command="delete" :disabled="row.review_state !== 'draft'">删除草稿</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </template>
        </el-table-column>
      </el-table>
      </div>

      <el-empty v-if="projectId && !listLoading && cases.length === 0" :description="libraryTab === 'review' ? '没有待评审用例' : libraryTab === 'archived' ? '归档区暂无用例' : '当前筛选条件下没有用例'">
        <el-button v-if="libraryTab !== 'all'" type="primary" plain @click="libraryTab='all';onLibraryTabChange()">查看全部用例</el-button>
        <template v-else-if="canCreateCase">
          <p class="empty-hint">可以逐条录入、批量迁移已有资产，或从需求和接口文档智能生成。</p>
          <div class="empty-actions">
            <el-button type="primary" :icon="Plus" @click="createVisible = true">新建用例</el-button>
            <el-button :icon="Upload" @click="importVisible = true">批量导入</el-button>
            <el-button :icon="MagicStick" @click="goCaseGeneration">智能生成</el-button>
          </div>
        </template>
      </el-empty>
      <el-empty v-if="!projectId" description="请先选择项目" />
      <el-pagination
        v-if="totalCases > pageSize"
        class="pagination"
        v-model:current-page="page"
        :page-size="pageSize"
        :total="totalCases"
        layout="prev, pager, next, total"
        @current-change="loadCases"
      />
    </el-card>

    <manual-case-drawer v-model="createVisible" :project-id="projectId" :project-name="projects.find(project => project.id === projectId)?.name || '当前项目'" @saved="onManualCaseSaved" />
    <case-import-dialog v-model="importVisible" :project-id="projectId" @imported="onCasesImported" />
    <case-review-submit-dialog v-model="reviewSubmitVisible" :project-id="projectId" :case-item="reviewSubmitCase" @submitted="onReviewSubmitted" />
    <case-review-task-drawer v-model="reviewTaskVisible" :task-id="activeReviewTaskId" @decided="onReviewDecided" />
    <manual-case-execution-dialog v-model="manualExecutionVisible" :case-item="manualExecutionCase" @completed="loadTraceability(manualExecutionCase.id)" />

    <el-drawer v-model="detailVisible" size="min(920px, 96vw)" destroy-on-close class="case-drawer">
      <template #header>
        <div class="drawer-heading">
          <div>
            <div class="drawer-title">{{ detailCase?.title || '用例详情' }}</div>
            <div class="drawer-subtitle">{{ sourceLabel(detailCase?.source) }} · v{{ detailCase?.version || 1 }} · {{ reviewLabel(detailCase || {}) }}</div>
          </div>
          <el-button v-if="!editing" type="primary" plain @click="startEditing">编辑用例</el-button>
        </div>
      </template>

      <div v-loading="detailLoading" class="drawer-content">
        <el-tabs v-model="detailTab">
          <el-tab-pane label="基本信息" name="overview">
            <el-form v-if="editing" label-position="top" class="editor-form">
              <el-form-item label="用例标题" required><el-input v-model="editor.title" maxlength="500" show-word-limit /></el-form-item>
              <el-form-item label="描述"><el-input v-model="editor.description" type="textarea" :rows="3" /></el-form-item>
              <div class="form-grid">
                <el-form-item label="优先级">
                  <el-select v-model="editor.priority"><el-option v-for="p in ['P0','P1','P2','P3']" :key="p" :label="p" :value="p" /></el-select>
                </el-form-item>
                <el-form-item label="执行类型">
                  <el-select v-model="editor.execution_kind"><el-option label="API 自动执行" value="api" /><el-option label="手工执行" value="manual" /></el-select>
                </el-form-item>
                <el-form-item label="业务归类"><el-input v-model="editor.folder" placeholder="例如：订单 / 认证" /></el-form-item>
                <el-form-item label="标签">
                  <el-select v-model="editor.tags" multiple filterable allow-create default-first-option placeholder="输入后回车">
                    <el-option v-for="tag in knownTags" :key="tag" :label="tag" :value="tag" />
                  </el-select>
                </el-form-item>
              </div>
              <el-alert v-if="detailCase?.review_state === 'approved'" type="warning" :closable="false" show-icon title="修改已批准用例后将重新进入草稿，需要再次评审。" />
            </el-form>
            <el-descriptions v-else :column="2" border>
              <el-descriptions-item label="标题" :span="2">{{ detailCase?.title }}</el-descriptions-item>
              <el-descriptions-item label="描述" :span="2">{{ detailCase?.description || '—' }}</el-descriptions-item>
              <el-descriptions-item label="执行类型">{{ detailCase?.execution_kind === 'manual' ? '手工执行' : 'API 自动执行' }}</el-descriptions-item>
              <el-descriptions-item label="优先级">{{ detailCase?.priority }}</el-descriptions-item>
              <el-descriptions-item label="业务归类">{{ detailCase?.folder || '未归类' }}</el-descriptions-item>
              <el-descriptions-item label="设计类型">{{ caseTypeLabel(detailCase?.case_type) }}</el-descriptions-item>
              <el-descriptions-item v-if="detailCase?.request_data?.requirement_ref" label="关联需求" :span="2">{{ detailCase.request_data.requirement_ref }}</el-descriptions-item>
              <el-descriptions-item label="标签" :span="2">
                <el-tag v-for="tag in detailCase?.tags || []" :key="tag" size="small" type="info" effect="plain" class="tag-gap">{{ tag }}</el-tag>
                <span v-if="!(detailCase?.tags || []).length">—</span>
              </el-descriptions-item>
              <el-descriptions-item label="创建时间">{{ formatTime(detailCase?.created_at) }}</el-descriptions-item>
              <el-descriptions-item label="最近更新">{{ formatTime(detailCase?.updated_at) }}</el-descriptions-item>
            </el-descriptions>
          </el-tab-pane>

          <el-tab-pane label="请求与断言" name="request">
            <template v-if="editing ? editor.execution_kind === 'manual' : detailCase?.execution_kind === 'manual'">
              <div class="section-title">前置条件</div>
              <el-input v-if="editing" v-model="editor.preconditions" type="textarea" :rows="3" maxlength="10000" placeholder="执行用例前需要满足的条件" />
              <p v-else class="manual-text">{{ detailCase?.request_data?.preconditions || '无' }}</p>
              <div class="section-title">执行步骤</div>
              <template v-if="editing">
                <div v-for="(step, index) in editor.manualSteps" :key="index" class="step-row">
                  <span>{{ index + 1 }}</span><el-input v-model="editor.manualSteps[index]" /><el-button text type="danger" @click="editor.manualSteps.splice(index, 1)">删除</el-button>
                </div>
                <el-button plain @click="editor.manualSteps.push('')"><el-icon><Plus /></el-icon>添加步骤</el-button>
                <el-form-item label="预期结果" class="manual-expected"><el-input v-model="editor.manualExpected" type="textarea" :rows="4" /></el-form-item>
              </template>
              <template v-else>
                <ol class="manual-steps"><li v-for="(step, index) in detailCase?.request_data?.steps || []" :key="index">{{ step }}</li></ol>
                <div class="section-title">预期结果</div><p class="manual-text">{{ detailCase?.expected_result?.text || '—' }}</p>
              </template>
            </template>

            <template v-else>
              <div class="request-line">
                <el-select v-if="editing" v-model="editor.method" class="method-select">
                  <el-option v-for="method in HTTP_METHODS" :key="method" :label="method" :value="method" />
                </el-select>
                <span v-else class="method-tag">{{ detailCase?.request_data?.method || 'GET' }}</span>
                <el-input v-if="editing" v-model="editor.url" placeholder="/api/orders/{id}" />
                <code v-else>{{ detailCase?.request_data?.url || '—' }}</code>
              </div>

              <el-tabs v-model="requestTab" type="border-card" class="request-tabs">
                <el-tab-pane label="Params" name="params"><key-value-editor :rows="editor.params" :editable="editing" @add="addKeyValue('params')" @remove="removeKeyValue('params', $event)" /></el-tab-pane>
                <el-tab-pane label="Headers" name="headers"><key-value-editor :rows="editor.headers" :editable="editing" @add="addKeyValue('headers')" @remove="removeKeyValue('headers', $event)" /></el-tab-pane>
                <el-tab-pane label="Body" name="body">
                  <el-radio-group v-if="editing" v-model="editor.bodyMode" size="small"><el-radio-button value="none">无</el-radio-button><el-radio-button value="json">JSON</el-radio-button><el-radio-button value="text">文本</el-radio-button></el-radio-group>
                  <el-input v-if="editing && editor.bodyMode !== 'none'" v-model="editor.bodyText" type="textarea" :rows="10" class="code-editor" :placeholder="bodyPlaceholder" />
                  <pre v-else-if="!editing" class="json-view">{{ prettyJson(detailCase?.request_data?.body) }}</pre>
                  <el-empty v-else description="该请求不发送 Body" :image-size="54" />
                </el-tab-pane>
                <el-tab-pane label="Auth" name="auth">
                  <template v-if="editing">
                    <el-select v-model="editor.auth.type" style="width: 200px"><el-option label="无认证" value="none" /><el-option label="Bearer Token" value="bearer" /><el-option label="Basic Auth" value="basic" /><el-option label="API Key" value="api_key" /></el-select>
                    <el-select v-if="editor.auth.type !== 'none'" v-model="selectedCredential" clearable filterable class="credential-picker" placeholder="引用已配置凭据（不展示密钥值）" @change="applyCredential"><el-option v-for="item in credentials" :key="`${item.scope}:${item.name}`" :label="`${item.name} · ${item.scope}`" :value="item.name" /></el-select>
                    <div v-if="editor.auth.type === 'bearer'" class="auth-fields"><el-input v-model="editor.auth.token" placeholder="变量占位符或实际 Token" show-password /></div>
                    <div v-if="editor.auth.type === 'basic'" class="auth-fields two-cols"><el-input v-model="editor.auth.username" placeholder="用户名" /><el-input v-model="editor.auth.password" placeholder="密码" show-password /></div>
                    <div v-if="editor.auth.type === 'api_key'" class="auth-fields api-key-grid"><el-input v-model="editor.auth.key" placeholder="参数名，如 X-API-Key" /><el-input v-model="editor.auth.value" placeholder="变量占位符或实际密钥" show-password /><el-select v-model="editor.auth.in"><el-option label="Header" value="header" /><el-option label="Query" value="query" /></el-select></div>
                  </template>
                  <el-descriptions v-else :column="1" border><el-descriptions-item label="认证类型">{{ authLabel(detailCase?.request_data?.auth?.type) }}</el-descriptions-item></el-descriptions>
                </el-tab-pane>
              </el-tabs>

              <div class="section-header"><div class="section-title">响应断言</div><el-button v-if="editing" size="small" plain @click="addAssertion"><el-icon><Plus /></el-icon>添加断言</el-button></div>
              <div class="status-assertion"><span>期望 HTTP 状态码</span><el-input-number v-if="editing" v-model="editor.expectedStatus" :min="100" :max="599" controls-position="right" /><strong v-else>{{ detailCase?.expected_result?.status_code || '未配置' }}</strong></div>
              <el-table :data="editor.assertions" size="small" class="assertion-table" empty-text="暂无附加断言">
                <el-table-column label="规则" width="150">
                  <template #default="{ row }"><el-select v-if="editing" v-model="row.type"><el-option label="JSON 路径" value="json_path" /><el-option label="包含文本" value="contains" /><el-option label="响应时间" value="response_time" /><el-option label="JSON Schema" value="jsonschema" /></el-select><span v-else>{{ assertionLabel(row.type) }}</span></template>
                </el-table-column>
                <el-table-column label="字段/条件" min-width="180">
                  <template #default="{ row }">
                    <el-input v-if="editing && row.type === 'json_path'" v-model="row.path" placeholder="$.data.id" />
                    <el-select v-else-if="editing && row.type === 'response_time'" v-model="row.operator"><el-option label="小于" value="lt" /></el-select>
                    <span v-else>{{ row.path || (row.type === 'response_time' ? '响应耗时' : '响应正文') }}</span>
                  </template>
                </el-table-column>
                <el-table-column label="比较" width="130">
                  <template #default="{ row }"><el-select v-if="editing && row.type === 'json_path'" v-model="row.operator"><el-option label="等于" value="equals" /><el-option label="存在" value="exists" /><el-option label="非空" value="not_null" /></el-select><span v-else>{{ row.operator || '—' }}</span></template>
                </el-table-column>
                <el-table-column label="期望值" min-width="180">
                  <template #default="{ row }"><el-input v-if="editing" v-model="row.value" :placeholder="row.type === 'response_time' ? '毫秒' : '期望值'" /><code v-else>{{ assertionValue(row) }}</code></template>
                </el-table-column>
                <el-table-column v-if="editing" width="60"><template #default="{ $index }"><el-button text type="danger" aria-label="删除断言" @click="editor.assertions.splice($index, 1)"><el-icon><Delete /></el-icon></el-button></template></el-table-column>
              </el-table>
            </template>
          </el-tab-pane>

          <el-tab-pane label="引用与结果" name="trace">
            <el-skeleton v-if="traceLoading" :rows="6" animated />
            <template v-else>
              <div class="trace-card"><div class="section-title">生成来源</div><el-descriptions :column="2" border><el-descriptions-item label="来源">{{ sourceLabel(traceability.source?.source) }}</el-descriptions-item><el-descriptions-item label="创建人">{{ traceability.source?.created_by_name || '—' }}</el-descriptions-item><el-descriptions-item v-if="traceability.source?.endpoint" label="接口" :span="2"><span class="method-tag">{{ traceability.source.endpoint.method }}</span>{{ traceability.source.endpoint.path }}<span v-if="traceability.source.endpoint.document_name" class="muted"> · {{ traceability.source.endpoint.document_name }}</span></el-descriptions-item><el-descriptions-item v-if="traceability.source?.requirement" label="需求文档" :span="2">{{ traceability.source.requirement.filename }}（{{ traceability.source.requirement.parse_engine || '未知解析引擎' }}）</el-descriptions-item></el-descriptions></div>
              <div class="trace-card"><div class="section-title">当前计划引用</div><el-table :data="traceability.plans || []" size="small" empty-text="尚未加入测试计划"><el-table-column prop="name" label="计划" /><el-table-column label="启用" width="80"><template #default="{ row }">{{ row.enabled ? '是' : '否' }}</template></el-table-column><el-table-column prop="status" label="状态" width="100" /></el-table></div>
              <div class="trace-card"><div class="section-title">计划版本引用</div><el-table :data="traceability.plan_revisions || []" size="small" empty-text="尚未被已发布计划版本引用"><el-table-column prop="plan_name" label="计划" /><el-table-column label="版本" width="80"><template #default="{ row }">r{{ row.revision }}</template></el-table-column><el-table-column prop="revision_status" label="状态" width="110" /><el-table-column label="发布时间" width="170"><template #default="{ row }">{{ formatTime(row.published_at) }}</template></el-table-column></el-table></div>
              <div class="trace-card"><div class="section-title">最近运行结果</div><el-table :data="traceability.recent_runs || []" size="small" empty-text="暂无可追溯运行；新执行会自动建立关联"><el-table-column label="结果" width="90"><template #default="{ row }"><el-tag size="small" :type="row.passed ? 'success' : 'danger'">{{ row.passed === null ? '未完成' : row.passed ? '通过' : '失败' }}</el-tag></template></el-table-column><el-table-column prop="status_code" label="HTTP" width="80" /><el-table-column prop="response_time_ms" label="耗时(ms)" width="100" /><el-table-column label="执行时间"><template #default="{ row }">{{ formatTime(row.executed_at) }}</template></el-table-column></el-table></div>
              <div class="trace-card"><div class="section-title">关联缺陷</div><el-table :data="traceability.defects || []" size="small" empty-text="暂无关联缺陷"><el-table-column label="缺陷" min-width="220"><template #default="{ row }"><el-button link type="primary" @click="$router.push(`/defects/${row.id}`)">{{ row.title }}</el-button></template></el-table-column><el-table-column prop="severity" label="严重度" width="100" /><el-table-column prop="status" label="状态" width="100" /></el-table></div>
            </template>
          </el-tab-pane>

          <el-tab-pane label="版本差异" name="versions">
            <div class="version-toolbar">
              <el-select v-model="compareLeft" placeholder="基准版本"><el-option v-for="version in versions" :key="`l-${version.version}`" :label="`v${version.version} · ${changeTypeLabel(version.change_type)}`" :value="version.version" /></el-select>
              <span>对比</span>
              <el-select v-model="compareRight" placeholder="目标版本"><el-option v-for="version in versions" :key="`r-${version.version}`" :label="`v${version.version} · ${changeTypeLabel(version.change_type)}`" :value="version.version" /></el-select>
            </div>
            <el-table :data="versionDiffRows" border empty-text="至少需要两个版本才能比较">
              <el-table-column prop="label" label="字段" width="120" />
              <el-table-column label="基准版本"><template #default="{ row }"><pre class="diff-value removed">{{ row.before }}</pre></template></el-table-column>
              <el-table-column label="目标版本"><template #default="{ row }"><pre class="diff-value added">{{ row.after }}</pre></template></el-table-column>
            </el-table>
          </el-tab-pane>

          <el-tab-pane label="评审任务" name="reviews">
            <el-table :data="caseReviewTasks" size="small" border empty-text="尚未发起评审任务">
              <el-table-column label="轮次" width="76"><template #default="{ row }">第 {{ row.round }} 轮</template></el-table-column>
              <el-table-column label="绑定版本" width="90"><template #default="{ row }">v{{ row.case_version }}</template></el-table-column>
              <el-table-column label="提交人" prop="submitter_name" min-width="110" />
              <el-table-column label="评审进度" width="100"><template #default="{ row }">{{ row.approved_count }}/{{ row.reviewer_count }}</template></el-table-column>
              <el-table-column label="状态" width="100"><template #default="{ row }"><el-tag size="small" :type="reviewTaskTagType(row.status)">{{ reviewTaskLabel(row.status) }}</el-tag></template></el-table-column>
              <el-table-column label="提交时间" width="170"><template #default="{ row }">{{ formatTime(row.submitted_at) }}</template></el-table-column>
              <el-table-column label="操作" width="80"><template #default="{ row }"><el-button link type="primary" @click="showReviewTask(row.id)">查看</el-button></template></el-table-column>
            </el-table>
          </el-tab-pane>
        </el-tabs>
      </div>

      <template #footer>
        <div class="drawer-footer">
          <template v-if="editing"><el-button @click="cancelEditing">取消</el-button><el-button type="primary" :loading="savingEdit" @click="saveEdit">保存新版本</el-button></template>
          <template v-else><el-button @click="detailVisible = false">关闭</el-button><el-button v-if="['draft', 'changes_requested'].includes(detailCase?.review_state)" type="primary" plain @click="submitReview(detailCase)">提交评审</el-button><el-button v-if="detailCase?.review_state === 'pending'" type="primary" plain @click="openReviewTask(detailCase)">查看评审任务</el-button><el-button v-if="detailCase?.status === 'adopted' && detailCase?.execution_kind === 'manual'" type="success" @click="openManualExecution(detailCase)">手工执行</el-button><el-button v-if="detailCase?.status === 'adopted' && detailCase?.execution_kind !== 'manual'" type="success" @click="openRun(detailCase)">运行</el-button></template>
        </div>
      </template>
    </el-drawer>

    <el-dialog v-model="batchFolderVisible" title="批量归类" width="440px"><el-form label-position="top"><el-form-item label="业务归类"><el-input v-model="batchFolder" placeholder="例如：订单 / 认证；留空可清除归类" /></el-form-item></el-form><template #footer><el-button @click="batchFolderVisible = false">取消</el-button><el-button type="primary" :loading="batchUpdating" @click="applyBatchFolder">保存</el-button></template></el-dialog>
    <el-dialog v-model="batchTagsVisible" title="批量添加标签" width="440px"><el-form label-position="top"><el-form-item label="标签"><el-select v-model="batchTags" multiple filterable allow-create default-first-option style="width: 100%" placeholder="输入标签后回车"><el-option v-for="tag in knownTags" :key="tag" :label="tag" :value="tag" /></el-select></el-form-item></el-form><template #footer><el-button @click="batchTagsVisible = false">取消</el-button><el-button type="primary" :loading="batchUpdating" @click="applyBatchTags">添加</el-button></template></el-dialog>

    <el-dialog v-model="reviewEventsVisible" title="用例评审记录" width="620px"><el-timeline v-if="reviewEvents.length"><el-timeline-item v-for="event in reviewEvents" :key="event.id" :timestamp="formatTime(event.created_at)">{{ reviewActionLabel(event.action) }}<span v-if="event.case_version"> · v{{ event.case_version }}</span> · {{ event.actor_name || event.actor_id }}<div v-if="event.comment">{{ event.comment }}</div></el-timeline-item></el-timeline><el-empty v-else description="尚无评审记录" /></el-dialog>

    <el-dialog v-model="addToPlanVisible" :title="addIntent === 'run' ? '运行用例' : '加入测试计划'" width="560px" destroy-on-close @open="loadPlansIfNeeded">
      <el-alert v-if="addIntent === 'run'" type="info" :closable="false" show-icon title="企业执行以已发布计划版本为准。加入后将前往测试计划页完成发布并选择环境运行。" />
      <el-form label-width="90px" class="plan-form">
        <el-form-item label="用例数量"><el-tag size="small" type="info">{{ addToPlanCaseIds.length }} 条</el-tag></el-form-item>
        <el-form-item label="处理方式"><el-radio-group v-model="planMode"><el-radio-button value="existing">已有计划</el-radio-button><el-radio-button value="new">新建计划</el-radio-button></el-radio-group></el-form-item>
        <el-form-item v-if="planMode === 'existing'" label="目标计划" required><el-select v-model="targetPlanId" filterable :loading="plansLoading" style="width: 100%" placeholder="选择测试计划"><el-option v-for="plan in plans" :key="plan.id" :label="plan.name" :value="plan.id" /></el-select></el-form-item>
        <template v-else><el-form-item label="计划名称" required><el-input v-model="newPlanName" placeholder="例如：订单核心回归" /></el-form-item><el-form-item label="说明"><el-input v-model="newPlanDesc" type="textarea" :rows="2" /></el-form-item></template>
      </el-form>
      <template #footer><el-button @click="addToPlanVisible = false">取消</el-button><el-button type="primary" :loading="addToPlanLoading" @click="submitAddToPlan">{{ addIntent === 'run' ? '加入并前往运行' : '确认加入' }}</el-button></template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, defineComponent, h, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElButton, ElCheckbox, ElInput, ElMessage, ElMessageBox } from 'element-plus'
import { Delete, MagicStick, MoreFilled, Plus, Upload } from '@element-plus/icons-vue'
import { caseApi, planApi, projectApi, secretApi } from '@/api'
import ManualCaseDrawer from '@/components/ManualCaseDrawer.vue'
import CaseImportDialog from '@/components/CaseImportDialog.vue'
import CaseReviewSubmitDialog from '@/components/cases/CaseReviewSubmitDialog.vue'
import CaseReviewTaskDrawer from '@/components/cases/CaseReviewTaskDrawer.vue'
import ManualCaseExecutionDialog from '@/components/cases/ManualCaseExecutionDialog.vue'
import { MANUAL_CASE_TYPES } from '@/types/manualCase'
import { useAuthStore } from '@/stores'

type KeyValueRow = { key: string; value: string; enabled: boolean }
type AssertionRow = { type: string; path: string; operator: string; value: string; raw?: any }

const KeyValueEditor = defineComponent({
  name: 'KeyValueEditor',
  props: { rows: { type: Array as () => KeyValueRow[], required: true }, editable: Boolean },
  emits: ['add', 'remove'],
  setup(props, { emit }) {
    return () => h('div', { class: 'kv-editor' }, [
      ...props.rows.map((row, index) => h('div', { class: 'kv-row', key: index }, [
        props.editable ? h(ElCheckbox, { modelValue: row.enabled, 'onUpdate:modelValue': (value: boolean | string | number) => { row.enabled = Boolean(value) } }) : null,
        props.editable ? h(ElInput, { modelValue: row.key, placeholder: '参数名', 'onUpdate:modelValue': (value: string) => { row.key = value } }) : h('code', row.key),
        props.editable ? h(ElInput, { modelValue: row.value, placeholder: '值（支持 {{variable}}）', 'onUpdate:modelValue': (value: string) => { row.value = value } }) : h('span', row.value),
        props.editable ? h(ElButton, { text: true, type: 'danger', onClick: () => emit('remove', index) }, () => '删除') : null,
      ])),
      props.editable ? h(ElButton, { plain: true, size: 'small', onClick: () => emit('add') }, () => '添加一行') : null,
      !props.editable && props.rows.length === 0 ? h('div', { class: 'empty-inline' }, '无') : null,
    ])
  },
})

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const canCreateCase = computed(() => ['super_admin', 'admin', 'test_manager', 'tester'].includes(auth.user?.role || ''))
const createVisible = ref(false)
const highlightedCaseId = ref('')
const caseTable = ref<any>()
const caseTableContainer = ref<HTMLElement>()
let highlightTimer: ReturnType<typeof setTimeout> | undefined
const HTTP_METHODS = ['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS']
const projects = ref<any[]>([])
const projectId = ref('')
const cases = ref<any[]>([])
const totalCases = ref(0)
const page = ref(1)
const pageSize = 50
const listLoading = ref(false)
const activeType = ref('all')
const activeSource = ref('')
const libraryTab = ref<'all' | 'review' | 'archived'>('all')
const searchKeyword = ref('')
const selectedRows = ref<any[]>([])
const batchAdopting = ref(false)

const detailVisible = ref(false)
const detailLoading = ref(false)
const detailCase = ref<any>(null)
const detailTab = ref('overview')
const requestTab = ref('params')
const editing = ref(false)
const savingEdit = ref(false)
const editor = ref<any>({
  title: '', description: '', priority: 'P2', execution_kind: 'api', folder: '', tags: [],
  method: 'GET', url: '/', params: [], headers: [], bodyMode: 'none', bodyText: '',
  auth: { type: 'none', token: '', username: '', password: '', key: '', value: '', in: 'header' },
  expectedStatus: 200, assertions: [], manualSteps: [], manualExpected: '',
})
const requestExtras = ref<any>({})
const expectedExtras = ref<any>({})
const versions = ref<any[]>([])
const compareLeft = ref<number | null>(null)
const compareRight = ref<number | null>(null)
const traceability = ref<any>({})
const traceLoading = ref(false)

const reviewEventsVisible = ref(false)
const reviewEvents = ref<any[]>([])
const reviewSubmitVisible = ref(false)
const reviewSubmitCase = ref<any>({})
const reviewTaskVisible = ref(false)
const activeReviewTaskId = ref('')
const caseReviewTasks = ref<any[]>([])
const manualExecutionVisible = ref(false)
const manualExecutionCase = ref<any>({})
const batchFolderVisible = ref(false)
const batchTagsVisible = ref(false)
const batchFolder = ref('')
const batchTags = ref<string[]>([])
const batchUpdating = ref(false)
const importVisible = ref(false)
const credentials = ref<any[]>([])
const selectedCredential = ref('')

const addToPlanVisible = ref(false)
const addToPlanLoading = ref(false)
const addToPlanCaseIds = ref<string[]>([])
const addIntent = ref<'add' | 'run'>('add')
const plans = ref<any[]>([])
const plansLoading = ref(false)
const targetPlanId = ref('')
const planMode = ref<'existing' | 'new'>('existing')
const newPlanName = ref('')
const newPlanDesc = ref('')

const SOURCE_LABELS: Record<string, string> = { requirement: '需求生成', ai_generated: 'AI 生成', manual: '人工创建' }
const SOURCE_TYPES: Record<string, any> = { requirement: 'warning', ai_generated: 'primary', manual: 'success' }
const PRIORITY_TYPES: Record<string, any> = { P0: 'danger', P1: 'warning', P2: '', P3: 'info' }

const knownTags = computed(() => Array.from(new Set(cases.value.flatMap((item: any) => item.tags || []))).sort())
const bodyPlaceholder = computed(() => editor.value.bodyMode === 'json' ? '{\n  "name": "{{name}}"\n}' : '请求正文')
const versionDiffRows = computed(() => {
  if (compareLeft.value === null || compareRight.value === null || compareLeft.value === compareRight.value) return []
  const left = versions.value.find((item) => item.version === compareLeft.value)?.snapshot || {}
  const right = versions.value.find((item) => item.version === compareRight.value)?.snapshot || {}
  const fields: Array<[string, string]> = [['title', '标题'], ['description', '描述'], ['priority', '优先级'], ['execution_kind', '执行类型'], ['folder', '业务归类'], ['tags', '标签'], ['request_data', '请求'], ['expected_result', '断言']]
  return fields.filter(([key]) => JSON.stringify(left[key]) !== JSON.stringify(right[key])).map(([key, label]) => ({ label, before: formatDiffValue(left[key]), after: formatDiffValue(right[key]) }))
})

function sourceLabel(value?: string) { return SOURCE_LABELS[value || ''] || value || '未知来源' }
function caseTypeLabel(value?: string) { return MANUAL_CASE_TYPES.find(type => type.value === value)?.label || value || '—' }
function caseRowClass({ row }: { row: any }) { return row.id === highlightedCaseId.value ? 'new-case-row' : '' }
async function onManualCaseSaved(asset: any) {
  libraryTab.value = 'all'; activeType.value = 'all'; activeSource.value = ''; searchKeyword.value = ''; page.value = 1
  selectedRows.value = []; caseTable.value?.clearSelection()
  highlightedCaseId.value = asset.id
  await loadCases()
  if (!cases.value.some(item => item.id === asset.id)) { cases.value.unshift(asset); totalCases.value += 1 }
  await nextTick()
  caseTableContainer.value?.querySelector('.new-case-row')?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  if (highlightTimer) clearTimeout(highlightTimer)
  highlightTimer = setTimeout(() => { highlightedCaseId.value = '' }, 15000)
}
onBeforeUnmount(() => { if (highlightTimer) clearTimeout(highlightTimer) })
function sourceType(value?: string) { return SOURCE_TYPES[value || ''] || 'info' }
function priorityType(value?: string) { return PRIORITY_TYPES[value || ''] || 'info' }
function reviewLabel(row: any) { if (row?.status === 'deprecated') return '已废弃'; return ({ draft: '草稿', pending: '待评审', approved: '已批准', changes_requested: '已退回' } as any)[row?.review_state] || row?.status || '—' }
function reviewTagType(row: any) { if (row?.status === 'deprecated') return 'danger'; return ({ pending: 'warning', approved: 'success', changes_requested: 'danger' } as any)[row?.review_state] || 'info' }
function formatTime(value?: string) { return value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '—' }
function prettyJson(value: any) { if (value === undefined || value === null || value === '') return '无'; return typeof value === 'string' ? value : JSON.stringify(value, null, 2) }
function formatDiffValue(value: any) { return typeof value === 'string' ? value || '—' : value === undefined ? '—' : JSON.stringify(value, null, 2) }
function authLabel(value?: string) { return ({ none: '无认证', bearer: 'Bearer Token', basic: 'Basic Auth', api_key: 'API Key' } as any)[value || 'none'] || value }
function assertionLabel(value: string) { return ({ status_code: '状态码', json_path: 'JSON 路径', contains: '包含文本', response_time: '响应时间', jsonschema: 'JSON Schema' } as any)[value] || value }
function assertionValue(row: any) { return row.type === 'response_time' ? `${row.max_ms ?? row.value} ms` : prettyJson(row.expected ?? row.schema ?? row.value) }
function changeTypeLabel(value: string) { return ({ created: '人工创建', imported: '导入', generated: '生成', baseline: '基线', edit: '编辑', classify: '归类', copied: '复制' } as any)[value] || value }
function reviewActionLabel(value: string) { return ({ submit: '提交评审', approve: '批准', changes_requested: '退回', cancel: '取消评审', edit: '编辑', deprecate: '废弃' } as any)[value] || value }
function reviewTaskLabel(value: string) { return ({ pending: '进行中', approved: '已通过', changes_requested: '需修改', cancelled: '已取消' } as any)[value] || value }
function reviewTaskTagType(value: string) { return ({ pending: 'warning', approved: 'success', changes_requested: 'danger', cancelled: 'info' } as any)[value] || 'info' }

function objectToRows(value: any): KeyValueRow[] { return value && !Array.isArray(value) && typeof value === 'object' ? Object.entries(value).map(([key, item]) => ({ key, value: typeof item === 'string' ? item : JSON.stringify(item), enabled: true })) : [] }
function rowsToObject(rows: KeyValueRow[]) { const output: Record<string, any> = {}; rows.filter((row) => row.enabled && row.key.trim()).forEach((row) => { output[row.key.trim()] = row.value }); return output }
function assertionToRow(item: any): AssertionRow { return { type: item.type || 'json_path', path: item.path || '', operator: item.operator || 'equals', value: item.type === 'response_time' ? String(item.max_ms ?? '') : item.type === 'jsonschema' ? JSON.stringify(item.schema || {}, null, 2) : typeof item.expected === 'string' ? item.expected : item.expected === undefined ? '' : JSON.stringify(item.expected), raw: item } }
function parseExpectedValue(value: string): any { const text = String(value ?? '').trim(); if (!text) return ''; try { return JSON.parse(text) } catch { return text } }

async function loadProjects() { try { const res: any = await projectApi.getList(); const data = res?.data ?? res; projects.value = Array.isArray(data) ? data : data?.list || data?.items || [] } catch { projects.value = [] } }
async function onProjectChange() { page.value = 1; selectedRows.value = []; plans.value = []; await Promise.all([loadCases(), loadCredentials()]) }
async function loadCredentials() { if (!projectId.value) { credentials.value = []; return } try { const res: any = await secretApi.list(projectId.value); credentials.value = res?.data?.items || [] } catch { credentials.value = [] } }
function applyCredential(name: string) { if (!name) return; const refValue = `{{credential:${name}}}`; if (editor.value.auth.type === 'bearer') editor.value.auth.token = refValue; else if (editor.value.auth.type === 'basic') editor.value.auth.password = refValue; else editor.value.auth.value = refValue }
function onFilterChange() { page.value = 1; loadCases() }
function onLibraryTabChange() { page.value = 1; selectedRows.value = []; loadCases() }
async function loadCases() {
  if (!projectId.value) { cases.value = []; totalCases.value = 0; return }
  listLoading.value = true
  try {
    if (libraryTab.value === 'review') {
      const res: any = await caseApi.reviewTasks({ project_id: projectId.value, scope: 'mine', status: 'pending', page: page.value, page_size: pageSize, case_type: activeType.value === 'all' ? undefined : activeType.value, source: activeSource.value || undefined, keyword: searchKeyword.value || undefined })
      const tasks = res?.data?.items || []
      cases.value = tasks.map((task: any) => ({
        ...(task.case || {}), ...(task.version?.snapshot || {}), id: task.case_asset_id,
        project_id: task.project_id, version: task.case_version, review_state: 'pending',
        status: 'draft', source: task.case?.source, review_task: task,
      }))
      totalCases.value = res?.data?.total || 0
    } else {
      const res: any = await caseApi.list({ project_id: projectId.value, page: page.value, page_size: pageSize, case_type: activeType.value === 'all' ? undefined : activeType.value, source: activeSource.value || undefined, keyword: searchKeyword.value || undefined, status: libraryTab.value === 'archived' ? 'deprecated' : undefined })
      cases.value = res?.data?.items || []
      totalCases.value = res?.data?.total || 0
    }
  } catch { cases.value = []; totalCases.value = 0 } finally { listLoading.value = false }
}
function onSelectionChange(rows: any[]) { selectedRows.value = rows }

function hydrateEditor(item: any) {
  const request = item?.request_data || {}; const expected = item?.expected_result || {}; const body = request.body
  const knownRequestKeys = new Set(['method', 'url', 'params', 'headers', 'body', 'auth', 'steps'])
  requestExtras.value = Object.fromEntries(Object.entries(request).filter(([key]) => !knownRequestKeys.has(key)))
  expectedExtras.value = Object.fromEntries(Object.entries(expected).filter(([key]) => !['status_code', 'assertions', 'text'].includes(key)))
  editor.value = {
    title: item?.title || '', description: item?.description || '', priority: item?.priority || 'P2', execution_kind: item?.execution_kind || 'api', folder: item?.folder || '', tags: [...(item?.tags || [])],
    method: String(request.method || 'GET').toUpperCase(), url: request.url || '/', params: objectToRows(request.params), headers: objectToRows(request.headers),
    bodyMode: body === undefined || body === null || body === '' ? 'none' : typeof body === 'string' ? 'text' : 'json', bodyText: body === undefined || body === null ? '' : typeof body === 'string' ? body : JSON.stringify(body, null, 2),
    auth: { type: request.auth?.type || 'none', token: request.auth?.token || '', username: request.auth?.username || '', password: request.auth?.password || '', key: request.auth?.key || '', value: request.auth?.value || '', in: request.auth?.in || 'header' },
    expectedStatus: expected.status_code ?? 200, assertions: (expected.assertions || []).map(assertionToRow), manualSteps: [...(request.steps || [])], manualExpected: expected.text || '', preconditions: request.preconditions || '',
  }
}

async function openDetail(row: any, edit = false) {
  detailVisible.value = true; detailLoading.value = true; detailTab.value = edit ? 'overview' : 'overview'; editing.value = edit
  try {
    const [detailRes, versionRes, reviewsRes] = await Promise.all([caseApi.get(row.id), caseApi.versions(row.id), caseApi.caseReviewTasks(row.id)]) as any[]
    if (detailRes?.data?.project_id && detailRes.data.project_id !== projectId.value) { detailVisible.value = false; ElMessage.warning('该用例不属于当前项目'); return }
    detailCase.value = detailRes?.data || row; versions.value = versionRes?.data?.items || []; caseReviewTasks.value = reviewsRes?.data || []; hydrateEditor(detailCase.value)
    compareRight.value = versions.value[0]?.version ?? null; compareLeft.value = versions.value[1]?.version ?? versions.value[0]?.version ?? null
    loadTraceability(row.id)
  } finally { detailLoading.value = false }
}
async function loadTraceability(id: string) { traceLoading.value = true; try { const res: any = await caseApi.traceability(id); traceability.value = res?.data || {} } catch { traceability.value = {} } finally { traceLoading.value = false } }
function startEditing() { hydrateEditor(detailCase.value); editing.value = true }
function cancelEditing() { editing.value = false; hydrateEditor(detailCase.value) }
function addKeyValue(type: 'params' | 'headers') { editor.value[type].push({ key: '', value: '', enabled: true }) }
function removeKeyValue(type: 'params' | 'headers', index: number) { editor.value[type].splice(index, 1) }
function addAssertion() { editor.value.assertions.push({ type: 'json_path', path: '$.', operator: 'equals', value: '' }) }

function buildAssertion(row: AssertionRow) {
  if (row.type === 'json_path') { const assertion: any = { type: 'json_path', path: row.path, operator: row.operator }; if (!['exists', 'not_null'].includes(row.operator)) assertion.expected = parseExpectedValue(row.value); return assertion }
  if (row.type === 'contains') return { type: 'contains', expected: String(row.value) }
  if (row.type === 'response_time') return { type: 'response_time', max_ms: Number(row.value) }
  if (row.type === 'jsonschema') { try { return { type: 'jsonschema', schema: JSON.parse(row.value || '{}') } } catch { throw new Error('JSON Schema 必须是合法 JSON') } }
  return row.raw || { type: row.type, expected: parseExpectedValue(row.value) }
}

async function saveEdit() {
  if (!editor.value.title.trim()) { ElMessage.warning('请输入用例标题'); return }
  let requestData: any; let expectedResult: any
  try {
    if (editor.value.execution_kind === 'manual') { requestData = { ...requestExtras.value, preconditions: editor.value.preconditions, steps: editor.value.manualSteps.map((step: string) => step.trim()).filter(Boolean) }; expectedResult = { ...expectedExtras.value, text: editor.value.manualExpected.trim() } }
    else {
      if (!editor.value.url.startsWith('/') || editor.value.url.startsWith('//')) throw new Error('请求 URL 必须是以 / 开头的相对路径')
      let body: any = undefined; if (editor.value.bodyMode === 'json') { try { body = JSON.parse(editor.value.bodyText || '{}') } catch { throw new Error('Body 必须是合法 JSON') } } else if (editor.value.bodyMode === 'text') body = editor.value.bodyText
      requestData = { ...requestExtras.value, method: editor.value.method, url: editor.value.url, params: rowsToObject(editor.value.params), headers: rowsToObject(editor.value.headers) }
      if (body !== undefined) requestData.body = body
      if (editor.value.auth.type !== 'none') requestData.auth = { ...editor.value.auth }
      expectedResult = { ...expectedExtras.value, status_code: Number(editor.value.expectedStatus), assertions: editor.value.assertions.map(buildAssertion) }
    }
  } catch (error: any) { ElMessage.error(error.message || '请检查请求和断言配置'); return }
  savingEdit.value = true
  try {
    await caseApi.update(detailCase.value.id, { title: editor.value.title.trim(), description: editor.value.description, priority: editor.value.priority, execution_kind: editor.value.execution_kind, folder: editor.value.folder, tags: editor.value.tags, request_data: requestData, expected_result: expectedResult })
    ElMessage.success('已保存为新版本'); editing.value = false; await loadCases(); await openDetail({ id: detailCase.value.id })
  } finally { savingEdit.value = false }
}

async function handleMore(command: string, row: any) { if (command === 'edit') return openDetail(row, true); if (command === 'assert') return router.push(`/case-assert/${row.id}`); if (command === 'copy') return copyCase(row); if (command === 'review-tasks') return openReviewTask(row); if (command === 'review-events') return showReviewEvents(row); if (command === 'submit') return submitReview(row); if (command === 'approve') return openReviewTask(row); if (command === 'plan') return openAddToPlan([row.id]); if (command === 'deprecate') return deprecate(row); if (command === 'delete') return deleteCase(row) }

function goCaseGeneration() { router.push({ path: '/case-generation', query: { project_id: projectId.value } }) }
async function onCasesImported() { libraryTab.value = 'all'; page.value = 1; await loadCases() }
async function copyCase(row: any) { const res: any = await caseApi.copy(row.id); ElMessage.success('已复制为草稿'); await loadCases(); if (res?.data) openDetail(res.data, true) }
function submitReview(row: any) { reviewSubmitCase.value = row; reviewSubmitVisible.value = true }
async function onReviewSubmitted(task: any) { await loadCases(); if (detailVisible.value) detailVisible.value = false; if (task?.id) showReviewTask(task.id) }
function showReviewTask(taskId: string) { activeReviewTaskId.value = taskId; reviewTaskVisible.value = true }
async function openReviewTask(row: any) {
  if (row.review_task?.id) { showReviewTask(row.review_task.id); return }
  const response: any = await caseApi.caseReviewTasks(row.id)
  const tasks = response?.data || []
  const task = tasks.find((item: any) => item.status === 'pending') || tasks[0]
  if (!task) { ElMessage.info('该用例尚未发起评审任务'); return }
  showReviewTask(task.id)
}
async function onReviewDecided() { await loadCases(); if (detailVisible.value && detailCase.value?.id) { const response: any = await caseApi.caseReviewTasks(detailCase.value.id); caseReviewTasks.value = response?.data || [] } }
async function showReviewEvents(row: any) { const res: any = await caseApi.reviewEvents(row.id); reviewEvents.value = res?.data || []; reviewEventsVisible.value = true }
async function deprecate(row: any) { try { await ElMessageBox.confirm(`确认废弃用例“${row.title}”？`, '废弃确认', { type: 'warning' }); await caseApi.deprecate(row.id); ElMessage.success('已废弃'); await loadCases() } catch { /* 取消 */ } }
async function restoreCase(row: any) { await caseApi.restore(row.id); ElMessage.success('已恢复为草稿，需要重新提交评审'); await loadCases() }
async function deleteCase(row: any) { try { await ElMessageBox.confirm(`确认删除草稿“${row.title}”？`, '删除确认', { type: 'warning' }); await caseApi.remove(row.id); ElMessage.success('已删除'); await loadCases() } catch { /* 取消 */ } }

async function batchAdopt() { if (libraryTab.value !== 'review' || selectedRows.value.some((row) => !row.review_task?.can_review)) { ElMessage.warning('只能批量处理指派给你的待评审任务'); return } batchAdopting.value = true; try { await caseApi.adoptBatch(selectedRows.value.map((row) => row.id)); ElMessage.success('已批量提交通过结论'); await loadCases() } finally { batchAdopting.value = false } }
function openBatchFolder() { batchFolder.value = ''; batchFolderVisible.value = true }
function openBatchTags() { batchTags.value = []; batchTagsVisible.value = true }
async function applyBatchFolder() { batchUpdating.value = true; try { await caseApi.batchUpdate({ ids: selectedRows.value.map((row) => row.id), folder: batchFolder.value }); ElMessage.success('批量归类完成'); batchFolderVisible.value = false; await loadCases() } finally { batchUpdating.value = false } }
async function applyBatchTags() { if (!batchTags.value.length) { ElMessage.warning('请至少填写一个标签'); return } batchUpdating.value = true; try { await caseApi.batchUpdate({ ids: selectedRows.value.map((row) => row.id), add_tags: batchTags.value }); ElMessage.success('标签已添加'); batchTagsVisible.value = false; await loadCases() } finally { batchUpdating.value = false } }

function openRun(row: any) { openAddToPlan([row.id], 'run') }
function openManualExecution(row: any) { manualExecutionCase.value = row; manualExecutionVisible.value = true }
function openAddToPlan(ids: string[], intent: 'add' | 'run' = 'add') { const chosen = cases.value.filter((item) => ids.includes(item.id)); if (chosen.some((item) => item.status !== 'adopted' || item.execution_kind === 'manual')) { ElMessage.warning('只有已批准的 API 用例可以加入自动计划'); return } addIntent.value = intent; addToPlanCaseIds.value = ids; targetPlanId.value = ''; planMode.value = 'existing'; newPlanName.value = ''; newPlanDesc.value = ''; addToPlanVisible.value = true }
async function loadPlansIfNeeded() { if (plans.value.length) return; plansLoading.value = true; try { const res: any = await planApi.list({ project_id: projectId.value, page: 1, page_size: 200 }); plans.value = res?.data?.list || []; if (!plans.value.length) planMode.value = 'new' } finally { plansLoading.value = false } }
async function submitAddToPlan() { let planId = targetPlanId.value; if (planMode.value === 'new') { if (newPlanName.value.trim().length < 2) { ElMessage.warning('计划名称至少 2 个字符'); return } addToPlanLoading.value = true; try { const res: any = await planApi.create({ project_id: projectId.value, name: newPlanName.value.trim(), description: newPlanDesc.value.trim() || undefined }); planId = res?.data?.id || '' } finally { addToPlanLoading.value = false } } if (!planId) { ElMessage.warning('请选择目标计划'); return } addToPlanLoading.value = true; try { await planApi.addCases(planId, addToPlanCaseIds.value); ElMessage.success(`已加入计划：${addToPlanCaseIds.value.length} 条用例`); addToPlanVisible.value = false; if (addIntent.value === 'run') router.push(`/projects/${projectId.value}/plans`) } finally { addToPlanLoading.value = false; addIntent.value = 'add' } }

onMounted(async () => {
  await loadProjects()
  const pid = String(route.query.project_id || '')
  if (pid && projects.value.some(project => project.id === pid)) {
    projectId.value = pid
    await onProjectChange()
    if (route.query.create === 'manual' && canCreateCase.value) createVisible.value = true
    else if (route.query.action === 'import' && canCreateCase.value) importVisible.value = true
    else if (route.query.review_task_id) showReviewTask(String(route.query.review_task_id))
    else if (route.query.case_id) await openDetail({ id: String(route.query.case_id) })
  }
})
</script>

<style scoped>
.case-library { display: flex; flex-direction: column; gap: 16px; }
.new-case-tag { margin-left: 8px; }.empty-hint { color: var(--el-text-color-secondary); font-size: 13px; }.manual-text { white-space: pre-wrap; word-break: break-word; }
:deep(.el-table .new-case-row td.el-table__cell) { background: var(--el-color-success-light-9); transition: background-color .3s; }
.library-header h2 { margin: 0; font-size: 20px; }.library-header p { margin: 6px 0 0; color: var(--el-text-color-secondary); font-size: 13px; }
.header-row, .filter-row, .batch-toolbar, .drawer-heading, .section-header, .request-line, .version-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.empty-actions { display: flex; justify-content: center; gap: 10px; flex-wrap: wrap; }
.project-picker { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }.project-picker .el-select { width: 240px; }
.filter-row { justify-content: flex-start; flex-wrap: wrap; margin-bottom: 14px; }.keyword-input { width: 280px; }.result-count { margin-left: auto; color: var(--el-text-color-secondary); font-size: 13px; }
.batch-toolbar { justify-content: flex-start; min-height: 42px; margin-bottom: 12px; padding: 0 12px; background: var(--el-color-primary-light-9); border: 1px solid var(--el-color-primary-light-7); border-radius: 6px; }
.case-title { padding: 0; color: var(--el-color-primary); font-weight: 600; text-align: left; background: none; border: 0; cursor: pointer; }.case-description { margin-top: 4px; color: var(--el-text-color-secondary); font-size: 12px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }.case-meta { display: flex; align-items: center; gap: 4px; margin-top: 6px; font-size: 12px; color: var(--el-text-color-secondary); }
.method-tag { display: inline-block; min-width: 46px; margin-right: 8px; color: var(--el-color-primary); font-size: 12px; font-weight: 700; }.method-post { color: var(--el-color-success); }.method-delete { color: var(--el-color-danger); }.method-put, .method-patch { color: var(--el-color-warning); }.url-text { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; word-break: break-all; }.manual-label, .version-label, .muted { color: var(--el-text-color-secondary); font-size: 12px; }.version-label { margin-top: 5px; }.pagination { margin-top: 16px; justify-content: flex-end; }
.drawer-heading { width: 100%; padding-right: 12px; }.drawer-title { max-width: 650px; font-size: 17px; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }.drawer-subtitle { margin-top: 4px; color: var(--el-text-color-secondary); font-size: 12px; }.drawer-content { min-height: 520px; }.drawer-footer { text-align: right; }.form-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 16px; }.tag-gap { margin-right: 5px; }
.request-line { justify-content: flex-start; margin-bottom: 14px; }.request-line .method-select { width: 120px; flex: none; }.request-line code { padding: 8px 10px; background: var(--el-fill-color-light); border-radius: 4px; font-size: 13px; }.request-tabs { margin-bottom: 22px; }.code-editor { margin-top: 10px; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }.json-view, .diff-value { margin: 0; padding: 10px; max-height: 280px; overflow: auto; white-space: pre-wrap; word-break: break-word; background: var(--el-fill-color-light); border-radius: 4px; font-size: 12px; }.section-title { margin: 16px 0 10px; font-weight: 600; }.section-header .section-title { margin-right: auto; }.status-assertion { display: flex; align-items: center; gap: 16px; margin-bottom: 10px; padding: 10px 12px; background: var(--el-fill-color-lighter); border-radius: 6px; }.assertion-table { margin-bottom: 12px; }
.kv-row { display: grid; grid-template-columns: 30px minmax(140px, 1fr) minmax(200px, 2fr) 56px; align-items: center; gap: 8px; margin-bottom: 8px; }.kv-row code { font-weight: 600; }.empty-inline { color: var(--el-text-color-secondary); }.auth-fields { margin-top: 12px; }.two-cols { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }.api-key-grid { display: grid; grid-template-columns: 1fr 1fr 120px; gap: 10px; }.step-row { display: grid; grid-template-columns: 24px 1fr 54px; align-items: center; gap: 8px; margin-bottom: 8px; }.manual-expected { margin-top: 18px; }.manual-steps { line-height: 2; }
.trace-card { margin-bottom: 22px; }.version-toolbar { justify-content: flex-start; margin-bottom: 14px; }.version-toolbar .el-select { width: 230px; }.diff-value.removed { background: var(--el-color-danger-light-9); }.diff-value.added { background: var(--el-color-success-light-9); }.plan-form { margin-top: 16px; }
.import-error { margin-left: 8px; color: var(--el-color-danger); font-size: 12px; }
.credential-picker { width: min(420px, 100%); margin-left: 10px; }
@media (max-width: 768px) { .header-row, .project-picker { align-items: flex-start; flex-direction: column; }.project-picker, .project-picker .el-select, .keyword-input { width: 100%; }.result-count { margin-left: 0; }.form-grid, .two-cols, .api-key-grid { grid-template-columns: 1fr; }.kv-row { grid-template-columns: 28px 1fr; }.kv-row > :nth-child(3) { grid-column: 2; }.drawer-title { max-width: 60vw; } }
</style>
