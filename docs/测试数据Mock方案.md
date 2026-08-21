# 测试数据 Mock 方案（能力13 · 后续规划）

> 状态：方案设计（本轮仅出方案，不写代码）
> 关联：设计文档 §9.8 曾规划 `mock/mock_server.py` + `DependencyMocker`（优先级 P3 / V2.0）。
> 当前 `app/modules/mock/` 仅有空 `__init__.py`。

## 1. 目标
- 在缺乏真实依赖/后端未就绪时，能**自动生成结构化假数据**并**暴露 Mock 端点**，让接口/集成测试可独立运行。
- 与用例生成联动：生成用例时自动引用 Mock 数据，提升可执行性。

## 2. 两种能力
### 2.1 静态假数据生成（Mock Data）
- 输入：`ApiSpec`（接口文档解析产物）或 `RequirementSpec`（需求解析产物）中的字段定义。
- 策略：
  - **规则生成**：按字段类型（string/int/enum/date/email…）生成合法值；按名称启发式（含 `id`→uuid、含 `email`→邮箱、含 `phone`→手机号、含 `name`→姓名）。
  - **AI 生成**：对语义复杂的字段，调用 `ModelRouter` 的 `mock` use_case 生成贴合业务的样例值。
- 输出：JSON 样例（请求体 / 响应体），可下载或写入用例。

### 2.2 Mock Server（Mock 端点）
- 暴露一个轻量 HTTP 服务（FastAPI `sub-application` 或独立端口），按 `ApiSpec` 注册路由：
  - `GET /mock/{path}` / `POST /mock/{path}` → 返回规则/AI 生成的响应体（可带动态参数、延迟模拟）。
  - 支持按场景切换响应（正常/错误/超时），供集成测试消费。
- 配置存 `mock_configs` 表（项目级，关联 ApiSpec）。

## 3. 模块结构（落地时）
```
app/modules/mock/
  __init__.py
  generator.py      # 字段级假数据生成（规则 + AI）
  mock_server.py    # 基于 ApiSpec 注册 Mock 端点
  schemas.py        # MockConfig / MockResponse
api/mock.py         # 上传 ApiSpec/需求 → 生成数据；启停 Mock Server；查看/编辑响应
```

## 4. 表设计（新增）
```sql
CREATE TABLE mock_configs (
  id UUID PRIMARY KEY,
  project_id UUID REFERENCES projects(id),
  spec_ref UUID,                 -- 关联 api_endpoints / requirement_docs
  base_path VARCHAR(200),
  strategy VARCHAR(20),          -- rule / ai
  responses JSONB,               -- 各接口预设响应
  is_active BOOLEAN DEFAULT false,
  created_at TIMESTAMP
);
```

## 5. 与用例生成的衔接
- `case_generator` 生成用例时，若目标接口在 `mock_configs` 中且 `is_active`，自动把 Mock URL 填入 `request_data` 的 host，用例即可在未接真实依赖时跑通。
- 需求解析（能力10）生成的用例，可同样引用 Mock 数据作为预期响应。

## 6. 实施步骤
1. `generator.py`：实现字段级规则生成 + AI 兜底（复用 `ModelRouter`）。
2. `api/mock.py`：上传 ApiSpec/需求 → 生成样例数据；CRUD 响应模板。
3. `mock_server.py`：基于 ApiSpec 注册端点，支持场景切换；提供启停接口。
4. 前端页：Mock 数据预览 / 响应编辑 / Mock Server 启停。
5. 与 `case_generator` 联动注入。

## 7. 工作量评估
- 后端：~4~6 人日（生成器、Mock Server、表与 API、用例联动）
- 前端：~2 人日（Mock 数据页 + Server 控制）
- 风险：Mock Server 端口/路由冲突、复杂响应模板的编辑体验。

## 8. 与现有能力的关系
- 依赖"接口文档解析（能力1）""需求文档解析（能力10）"产出的结构化 Spec 作为输入。
- 与覆盖率（能力11）无直接耦合；Mock 本身不计入覆盖率（属测试桩）。
