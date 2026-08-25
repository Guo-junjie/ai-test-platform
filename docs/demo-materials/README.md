# demo-materials — AI 测试平台 4 项解析功能 demo 资料

| 文件 | 用途 | 对应 API |
|---|---|---|
| `openapi.json` | 接口文档（OpenAPI 3.0.3 规范），10 个电商订单中心接口 | `POST /api/docs/upload` + `/{id}/parse` |
| `requirement.md` | 需求文档（Markdown 格式），含 12 条 FR + 验收点 | `POST /api/requirements` |
| `code-sample/main.py` | FastAPI 示例代码（7 个路由） | `POST /api/analysis/run` |
| `../ai-test-platform/backend/scripts/verify_parse_pipeline.py` | 部署机一键验证脚本 | — |

## 业务域

电商订单中心「**e2e-demo-project**」：
- 用户：注册 / 登录 / Refresh / 信息查询 / 改密（5 接口）
- 商品：列表 / 详情（2 接口）
- 订单：创建 / 详情 / 支付 / 取消（4 接口）

总计 **11 接口 + 12 条 FR + 10 个验收用例**。

## 部署机一键跑

把整个目录传到部署机：

```bash
# 1. 上传 demo 资料到部署机 gjj 用户家目录
scp -r demo-materials gjj@gjj-virtual-machine:~/demo-materials

# 2. 把代码解析材料也放到 backend 容器可读的目录（最简单的 /tmp）
ssh gjj@gjj-virtual-machine "cp -r ~/demo-materials/code-sample /tmp/code-sample"
ssh gjj@gjj-virtual-machine "cp ~/demo-materials/openapi.json ~/demo-materials/requirement.md /tmp/"

# 3. 跑端到端验证脚本
ssh gjj@gjj-virtual-machine "cd /opt/ai-test-platform && \
  docker compose exec -T backend python -m scripts.verify_parse_pipeline --code-path /tmp/code-sample"
```

预期输出：

```
[1/6] 登录 superadmin                     ✅
[2/6] 取 e2e-demo-project UUID            ✅
[3/6] 上传接口文档(openapi.json)          ✅
[3.5/6] 解析接口文档                       ✅ endpoints=11
[4/6] AI 评审该接口文档                   ✅ overall_score=82
[5/6] 上传需求文档(requirement.md)        ✅ 需求数=12
[5.5/6] 基于需求生成测试用例               ✅ 5 条
[6/6] 代码解析(/tmp/code-sample)          ✅ python_fastapi, API=7
🎉 全流程跑完
```

## 4 项功能手工触发

### ① 接口文档解析（上传 + 解析 + 导入接口）

```bash
# UI：知识库→接口资产→上传 OpenAPI 文档

# API 触发：
PROJECT_ID="<UUID>"   # 用 GET /api/projects 查 e2e-demo-project
curl -X POST http://localhost:8000/api/docs/upload \
  -H "Authorization: Bearer $TOKEN" \
  -F "project_id=$PROJECT_ID" \
  -F "doc_type=openapi" \
  -F "file=@demo-materials/openapi.json"
# 返回 doc_id
curl -X POST http://localhost:8000/api/docs/$DOC_ID/parse \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"use_ai":true,"max_endpoints":50}'
# 解析后导入到项目接口资产：
curl -X POST http://localhost:8000/api/docs/$DOC_ID/import \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{}'
```

### ② 接口文档评审

```bash
# UI：接口资产→某文档右侧「评审」按钮

# API 触发（评审整份文档）：
curl -X POST http://localhost:8000/api/docs/reviews \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"project_id\":\"$PROJECT_ID\",\"doc_id\":\"$DOC_ID\"}"

# 查看某次评审：
curl http://localhost:8000/api/docs/reviews/$REVIEW_ID \
  -H "Authorization: Bearer $TOKEN"
```

### ③ 需求文档解析（+自动生成用例）

```bash
# UI：需求文档→上传 .md / .docx / .pdf
curl -X POST http://localhost:8000/api/requirements \
  -H "Authorization: Bearer $TOKEN" \
  -F "project_id=$PROJECT_ID" \
  -F "use_ai=true" \
  -F "file=@demo-materials/requirement.md"

# 上传成功后基于需求生成用例：
curl -X POST http://localhost:8000/api/requirements/$REQ_ID/generate-cases \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"count":5}'
```

### ④ 代码解析

```bash
# ⚠️ local_path 必须是 backend 容器**能访问到的绝对路径**。
# 最简：把代码工程传到 /tmp/code-sample
ssh gjj@gjj-virtual-machine "mkdir -p /tmp/code-sample && \
  ls /tmp/code-sample"
# 在 gjj 用户下解压代码工程到该目录后：

curl -X POST http://localhost:8000/api/analysis/run \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"local_path":"/tmp/code-sample"}'
```

返回示例：
```json
{
  "code": 0,
  "data": {
    "tech_stack": {"stack": "python_fastapi", "language": "python", "framework": "fastapi"},
    "apis": [
      {"method": "POST", "path": "/api/v1/users/register", "summary": "用户注册"},
      {"method": "POST", "path": "/api/v1/users/login", ...},
      ...
    ],
    "ai_analysis": {
      "business_modules": [...],
      "data_flow": {...},
      "risk_areas": [...]
    },
    "total_apis": 7
  }
}
```

## 关键提示

1. **`POST /api/analysis/run` 必须信任容器挂载的路径**：本平台 backend 容器默认挂载 `/workspace` 或宿主机的 `/tmp`——具体看 `docker-compose.yml` 的 volumes。`code-sample` 这套目录能放在 backend 容器的任何可读路径即可。

2. **`POST /api/requirements/{id}/generate-cases` 必须跑过完整的 seed_e2e** 否则 `test_case_assets` 已有 10 条历史用例，本功能会基于历史 + 需求生成增量。

3. **AI 模型配置**：四个 AI 类功能（解析/评审/代码分析/需求→用例）都依赖 `/api/models` 配好的 LLM。如果还没配，解析/评审都会自动降级为「规则模式」（仍能跑通，但返回内容更简略）。
