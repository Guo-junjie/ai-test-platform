# 知识库 RAG 接入方案（能力12 · 后续规划）

> 状态：方案设计（本轮仅出方案，不写代码）
> 关联：MVP 阶段设计文档已明确「不接 RAG，仅基于当前 request/response/logs 分析」；本方案为后续增强。

## 1. 目标
为缺陷分析、用例生成、文档解析提供**历史经验召回**能力，解决当前"每次从零分析"的痛点：
- 缺陷定位更准（相似历史缺陷直接召回根因/修复方案）
- 用例生成更贴合团队历史场景，减少"通用但无效"的用例
- 需求/接口解析可结合业务术语表，提升结构化准确率

## 2. 总体架构
```
[数据来源] → [切片 Chunking] → [Embedding] → [向量库 pgvector]
                                                    │
[检索 Retriever] ← 查询(当前缺陷/需求/接口) ← [缺陷分析/用例生成/文档解析]
        │
   top-k chunks 拼入 prompt 注入 use_case 模型
```
- **复用现有 Postgres 16**：启用 `pgvector` 扩展，避免引入新组件（与现有 `postgres:16-alpine` 兼容，需镜像带 pgvector 或 init 时 `CREATE EXTENSION vector`）。
- **Embedding 模型**：复用 `ModelRouter` 增加一个 `embedding` use_case，优先用配置中的文本嵌入模型（OpenAI `text-embedding-3-small` / 本地 bge 等）；若无，提供降级（关键词 BM25 检索兜底）。

## 3. 数据来源（知识库内容）
| 来源 | 表/模块 | 说明 |
|------|---------|------|
| 历史缺陷 | `defect_analyzer` 产出 + `defects` 表 | 缺陷现象、根因、修复方案 |
| 历史用例 | `test_cases` / `case_library` | 已验证有效的用例模板 |
| 接口资产 | `api_endpoints` + `interface_docs` | 接口契约、字段含义 |
| 业务术语表 | 新增 `knowledge_terms` | 业务词 → 技术含义映射（人工维护） |

## 4. 表设计（新增）
```sql
CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE knowledge_chunks (
  id UUID PRIMARY KEY,
  kb_type VARCHAR(20),          -- defect / case / doc / term
  source_ref VARCHAR(200),      -- 来源 id
  content TEXT,                 -- 切片文本
  embedding vector(1536),       -- 向量
  meta JSONB,
  created_at TIMESTAMP
);
CREATE INDEX ON knowledge_chunks USING ivfflat (embedding vector_cosine_ops);
```

## 5. 检索注入点（最小改动）
- `defect_analyzer/analyzer.py`：分析前按"错误日志摘要"检索相似历史缺陷，拼入 prompt。
- `case_generator`：生成用例前按"接口/需求"检索历史用例，作为 few-shot。
- `doc_parser/ai_enhancer` 与 `requirement_parser`：解析前检索业务术语表，提升抽取准确率。
- 所有注入复用现有 `use_case` 模型路由，不改模型调用框架。

## 6. 实施步骤
1. Postgres 启用 pgvector（改 Dockerfile / init sql）。
2. 新增 `app/modules/knowledge/`（embedder / chunker / retriever）+ 两张表 + CRUD。
3. 提供"重建知识库"管理接口（全量切片嵌入）。
4. 在 3 个注入点加 `retrieve_and_inject()`，带开关（默认关，避免无知识库时报错）。
5. 管理页：知识库状态、重建按钮、术语表维护。

## 7. 工作量评估
- 后端：~5~7 人日（向量表、切片、检索、3 处注入、重建任务）
- 前端：~2 人日（知识库状态页 + 术语表维护）
- 风险：pgvector 镜像、Embedding 模型成本/可用性。

## 8. 与现有能力的关系
- 与"需求文档解析（能力10）""覆盖率（能力11）"正交，可并行推进。
- 知识库是**横切增强**，不阻塞主线功能。
