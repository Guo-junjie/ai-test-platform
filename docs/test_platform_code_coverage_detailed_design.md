# 测试平台代码覆盖率子系统详细设计文档

**版本：V1.0**  
**定位：可真实落地的代码覆盖率平台技术设计基线**  
**目标：实现项目代码覆盖率采集、统一解析、实时状态、统计、趋势、Diff、质量门禁，并为后续知识库和 AI 分析提供数据基础。**

---

## 1. 建设背景

测试平台需要解决：

- 不同项目使用不同覆盖率工具，结果无法统一管理。
- 测试执行结束后只能看到一次性报告，缺少平台级统计。
- 无法快速定位低覆盖率文件、函数、代码行和分支。
- 无法判断新增代码是否被测试覆盖。
- 无法关联 Git Commit、测试执行、测试用例和缺陷。
- 无法在 CI/CD 中统一执行 Coverage Gate。
- 无法基于历史 Coverage 判断测试风险。

因此建设独立的 **Code Coverage Service**。

核心原则：

> 覆盖率工具负责采集，平台负责标准化、存储、计算、对比、分析和展示。

---

# 2. 总体目标

平台至少提供：

1. 项目级覆盖率
2. Build 级覆盖率
3. Test Run 级覆盖率
4. 文件级覆盖率
5. 函数/方法级覆盖率
6. 行覆盖率
7. 分支覆盖率
8. 新增代码覆盖率
9. Coverage Trend
10. Coverage Diff
11. Coverage Gate
12. 未覆盖代码定位
13. CI/CD 集成
14. API 查询
15. 实时任务状态
16. 覆盖率风险分析
17. 与测试用例、Git、缺陷、知识库关联

---

# 3. 总体架构

```text
                         Git Repository
                               |
                               v
                        CI/CD Pipeline
                               |
                    +----------+----------+
                    |                     |
                    v                     v
              Test Execution        Build/Compile
                    |
                    v
            Coverage Instrumentation
                    |
             +------+------+
             |             |
             v             v
        coverage.xml    jacoco.xml
        lcov.info       profraw
             |             |
             +------+------+
                    |
                    v
           Coverage Collector
                    |
                    v
             Coverage Parser
                    |
                    v
          Coverage Normalizer
                    |
                    v
            Coverage Service
                    |
          +---------+----------+
          |         |          |
          v         v          v
      PostgreSQL  ObjectStore Redis
          |
          v
      Analysis Engine
          |
   +------+------+-------+------+
   |      |      |       |      |
   v      v      v       v      v
 Trend   Diff   Gate   Risk   Hotspot
   |      |      |       |      |
   +------+------+-------+------+
          |
          v
        FastAPI
          |
     +----+---------+
     |              |
     v              v
   Vue3          AI Service
Dashboard       / Knowledge
```

---

# 4. 推荐技术栈

## 后端

```text
Python 3.12+
FastAPI
SQLAlchemy 2.x
Pydantic
Alembic
```

## 数据库

```text
PostgreSQL
```

## 缓存

```text
Redis
```

## 异步任务

```text
Celery
```

## 文件存储

```text
MinIO / S3
```

## 前端

```text
Vue 3
TypeScript
Element Plus
ECharts
```

## 覆盖率工具

```text
Python      coverage.py / pytest-cov
Java        JaCoCo
JavaScript  Istanbul / c8
C/C++       llvm-cov / gcov
```

第一阶段只实现 Python Parser，后续增加其他语言。

---

# 5. 为什么必须设计统一 Coverage Model

不同工具输出格式不同：

```text
Python → coverage.xml
Java → jacoco.xml
JS → lcov.info
C/C++ → llvm-cov
```

平台不能让业务层直接处理这些格式。

必须：

```text
原始报告
   |
   v
Parser
   |
   v
统一 CoverageReport
   |
   v
Coverage Service
```

统一模型示例：

```python
class CoverageReport:
    project_id: int
    build_id: int
    commit_id: str
    branch: str

    line_total: int
    line_covered: int

    branch_total: int
    branch_covered: int

    function_total: int
    function_covered: int

    files: list
```

---

# 6. Coverage 数据层级

```text
Project
  |
  +-- Build
       |
       +-- Test Run
            |
            +-- Coverage Run
                 |
                 +-- Summary
                 |
                 +-- File
                      |
                      +-- Function
                      +-- Line
                      +-- Branch
```

这套层级非常重要，因为以后要回答：

- 哪个项目？
- 哪次构建？
- 哪次测试？
- 哪个文件？
- 哪个函数？
- 哪一行？
- 哪个分支？

---

# 7. 数据库设计

## 7.1 projects

```sql
CREATE TABLE projects (
    id BIGSERIAL PRIMARY KEY,
    name VARCHAR(128) NOT NULL,
    code VARCHAR(64) UNIQUE NOT NULL,
    repository_url TEXT,
    default_branch VARCHAR(128),
    language VARCHAR(64),
    status VARCHAR(32) DEFAULT 'active',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

## 7.2 builds

```sql
CREATE TABLE builds (
    id BIGSERIAL PRIMARY KEY,
    project_id BIGINT NOT NULL REFERENCES projects(id),
    build_number VARCHAR(128),
    branch VARCHAR(256),
    commit_id VARCHAR(128),
    commit_message TEXT,
    author VARCHAR(256),
    pipeline_id VARCHAR(256),
    status VARCHAR(32),
    started_at TIMESTAMP,
    finished_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

## 7.3 test_runs

```sql
CREATE TABLE test_runs (
    id BIGSERIAL PRIMARY KEY,
    project_id BIGINT NOT NULL REFERENCES projects(id),
    build_id BIGINT REFERENCES builds(id),
    framework VARCHAR(64),
    total INT DEFAULT 0,
    passed INT DEFAULT 0,
    failed INT DEFAULT 0,
    skipped INT DEFAULT 0,
    duration_ms BIGINT,
    status VARCHAR(32),
    started_at TIMESTAMP,
    finished_at TIMESTAMP
);
```

## 7.4 coverage_runs

```sql
CREATE TABLE coverage_runs (
    id BIGSERIAL PRIMARY KEY,
    project_id BIGINT NOT NULL REFERENCES projects(id),
    build_id BIGINT REFERENCES builds(id),
    test_run_id BIGINT REFERENCES test_runs(id),

    tool VARCHAR(64),
    tool_version VARCHAR(64),

    line_total BIGINT DEFAULT 0,
    line_covered BIGINT DEFAULT 0,
    line_rate NUMERIC(8,5),

    branch_total BIGINT DEFAULT 0,
    branch_covered BIGINT DEFAULT 0,
    branch_rate NUMERIC(8,5),

    function_total BIGINT DEFAULT 0,
    function_covered BIGINT DEFAULT 0,
    function_rate NUMERIC(8,5),

    statement_total BIGINT DEFAULT 0,
    statement_covered BIGINT DEFAULT 0,
    statement_rate NUMERIC(8,5),

    report_path TEXT,

    status VARCHAR(32),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

## 7.5 coverage_files

```sql
CREATE TABLE coverage_files (
    id BIGSERIAL PRIMARY KEY,
    coverage_run_id BIGINT NOT NULL REFERENCES coverage_runs(id),
    file_path TEXT NOT NULL,

    line_total BIGINT DEFAULT 0,
    line_covered BIGINT DEFAULT 0,
    line_rate NUMERIC(8,5),

    branch_total BIGINT DEFAULT 0,
    branch_covered BIGINT DEFAULT 0,
    branch_rate NUMERIC(8,5),

    function_total BIGINT DEFAULT 0,
    function_covered BIGINT DEFAULT 0,
    function_rate NUMERIC(8,5),

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

## 7.6 coverage_lines

大型项目建议分区。

```sql
CREATE TABLE coverage_lines (
    id BIGSERIAL,
    coverage_run_id BIGINT NOT NULL,
    coverage_file_id BIGINT NOT NULL,

    line_number INT NOT NULL,
    hit_count BIGINT DEFAULT 0,
    status VARCHAR(16),

    PRIMARY KEY (id, coverage_run_id)
) PARTITION BY RANGE (coverage_run_id);
```

状态：

```text
COVERED
MISSED
```

## 7.7 coverage_branches

```sql
CREATE TABLE coverage_branches (
    id BIGSERIAL PRIMARY KEY,
    coverage_run_id BIGINT NOT NULL,
    coverage_file_id BIGINT NOT NULL,
    line_number INT,
    branch_index INT,
    hit_count BIGINT DEFAULT 0,
    status VARCHAR(16)
);
```

## 7.8 coverage_functions

```sql
CREATE TABLE coverage_functions (
    id BIGSERIAL PRIMARY KEY,
    coverage_run_id BIGINT NOT NULL,
    coverage_file_id BIGINT NOT NULL,
    function_name VARCHAR(512),
    start_line INT,
    end_line INT,
    hit_count BIGINT DEFAULT 0,
    status VARCHAR(16)
);
```

---

# 8. 原始报告存储

不要把原始 Coverage HTML/XML 全部直接存 PostgreSQL。

推荐：

```text
MinIO / S3
```

目录：

```text
coverage/
  project-100/
    build-1024/
      coverage.xml
      htmlcov.zip
```

数据库保存：

```text
report_path
file_hash
tool
tool_version
```

---

# 9. Coverage 上传方案

第一版不要开发复杂 Agent。

推荐：

```text
CI/CD
 |
 +-- pytest
 |
 +-- coverage.xml
 |
 +-- POST /api/v1/coverage/upload
 |
 v
Coverage Platform
```

Python：

```bash
pytest   --cov=src   --cov-report=xml:coverage.xml   --cov-report=html:htmlcov
```

上传：

```bash
curl -X POST   -H "Authorization: Bearer ${TOKEN}"   -F "project_id=100"   -F "build_id=2001"   -F "test_run_id=3001"   -F "file=@coverage.xml"   http://coverage-platform/api/v1/coverage/upload
```

返回：

```json
{
  "coverage_run_id": 1024,
  "task_id": "task-abc",
  "status": "PROCESSING"
}
```

---

# 10. Coverage Parser 设计

定义统一接口：

```python
class CoverageParser:

    def supports(self, file_path: str) -> bool:
        raise NotImplementedError

    def parse(self, file_path: str) -> CoverageReport:
        raise NotImplementedError
```

Python：

```python
class CoverageXmlParser(CoverageParser):

    def supports(self, file_path):
        return file_path.endswith(".xml")

    def parse(self, file_path):
        ...
```

Java：

```python
class JacocoParser(CoverageParser):
    ...
```

JS：

```python
class LcovParser(CoverageParser):
    ...
```

---

# 11. Parser Factory

```python
class CoverageParserFactory:

    parsers = [
        CoverageXmlParser(),
        JacocoParser(),
        LcovParser(),
    ]

    @classmethod
    def get_parser(cls, file_path):
        for parser in cls.parsers:
            if parser.supports(file_path):
                return parser

        raise ValueError("Unsupported coverage report")
```

这样新增语言不需要修改核心 Coverage Service。

---

# 12. Coverage Pipeline

```text
UPLOAD
  |
  v
VALIDATE
  |
  v
DETECT FORMAT
  |
  v
PARSE
  |
  v
NORMALIZE
  |
  v
CALCULATE SUMMARY
  |
  v
SAVE
  |
  v
DIFF
  |
  v
GATE
  |
  v
RISK ANALYSIS
  |
  v
SUCCESS
```

任务状态：

```text
PENDING
RUNNING
PARSING
NORMALIZING
SAVING
ANALYZING
SUCCESS
FAILED
CANCELLED
```

---

# 13. 实时统计设计

这里的“实时”建议定义为：

## V1：测试完成后秒级更新

```text
Test Finished
 ↓
Coverage Report
 ↓
Upload
 ↓
Parse
 ↓
Save
 ↓
Dashboard刷新
```

这是最可靠的方案。

## V2：测试执行过程实时快照

Agent 每 5~10 秒上报：

```text
当前测试状态
当前Coverage快照
```

前端显示：

```text
测试进行中

71.2%
 ↓
74.5%
 ↓
78.3%
```

不要在 V1 实现逐行实时数据库写入，否则数据库压力和系统复杂度都会明显增加。

---

# 14. Redis 任务状态

Key：

```text
coverage:task:{task_id}
```

Value：

```json
{
  "status": "PARSING",
  "stage": "parser",
  "progress": 65,
  "coverage_run_id": 1024
}
```

V1 前端：

```text
GET /api/v1/tasks/{task_id}
```

V2：

```text
WebSocket
```

---

# 15. 覆盖率计算规则

不要完全相信原始报告中的比例。

平台重新计算：

```text
Line Rate =
line_covered / line_total

Branch Rate =
branch_covered / branch_total

Function Rate =
function_covered / function_total
```

特殊情况：

```text
total = 0
```

建议：

```text
rate = NULL
```

而不是 0%。

数据校验：

```text
covered <= total
```

否则：

```text
status = INVALID
```

---

# 16. 路径标准化

CI 环境可能产生：

```text
Windows:
C:\workspace\project\src\device.py

Linux:
/build/project/src/device.py
```

平台统一：

```text
src/device.py
```

建议基于：

```text
repository root
commit
source mapping
```

进行标准化。

否则不同机器生成的 Coverage 无法正确 Diff。

---

# 17. 幂等设计

同一报告可能重复上传。

推荐使用：

```text
file_hash
+
project_id
+
build_id
+
tool
```

作为幂等依据。

例如：

```text
project_id=100
build_id=2001
tool=coverage.py
file_hash=abc123
```

再次上传：

```text
返回已有 coverage_run
```

而不是产生重复数据。

---

# 18. Coverage Dashboard

首页：

```text
项目：DevicePlatform

+----------+----------+----------+----------+
| 行覆盖率 | 分支覆盖 | 函数覆盖 | 测试通过率 |
| 82.6%    | 71.4%    | 88.2%    | 96.7%      |
+----------+----------+----------+----------+

Coverage Trend
90% |
80% |       /----70% | -----/      \----
    +-------------------
       Build  Build  Build

最近构建
Build 1024    82.6%    +1.3%
Build 1023    81.3%    -0.8%
```

---

# 19. 文件级覆盖率

```text
src/
├── device.py        94.2%
├── user.py          89.1%
├── network.py       61.4%
├── snmp.py          45.3%   WARNING
└── service.py       92.4%
```

支持：

- 搜索
- 排序
- 模块过滤
- 语言过滤
- 覆盖率区间过滤

---

# 20. 函数级覆盖率

```text
device.py

add_device()       100%
delete_device()     42%   WARNING
update_device()     87%
get_device()        93%
```

点击函数进入源码视图。

---

# 21. 行级覆盖率

例如：

```text
120  def delete_device(device_id):
121      device = get_device(device_id)
122      if not device:
123          raise DeviceNotFound()
124
125      if device.status == "ONLINE":
126          raise DeviceOnlineError()
127
128      delete(device)
```

平台展示：

```text
123 MISSED
126 MISSED
```

---

# 22. Branch Coverage

显示：

```text
if device.status == ONLINE

True   ✓
False  ✗
```

这样可以识别：

> 总行覆盖率很高，但异常/条件分支没有覆盖。

---

# 23. Coverage Trend

按照：

```text
project
branch
time
```

查询：

```text
Build      Line Coverage
1001       71.2%
1002       74.1%
1003       76.8%
1004       75.4%
1005       82.6%
```

支持：

```text
7天
30天
90天
自定义
```

---

# 24. Coverage Diff

比较：

```text
Base Commit
      vs
Current Commit
```

计算：

```text
新增代码
删除代码
修改代码
新增覆盖
新增未覆盖
```

示例：

```text
新增代码：152行
已覆盖：102行
未覆盖：50行

New Code Coverage：
67.1%
```

---

# 25. New Code Coverage

平台必须重点展示：

```text
全量 Coverage：82.6%

新增代码 Coverage：51.3%
```

这样即使全量 Coverage 很高，也能发现新代码测试不足。

---

# 26. Coverage Diff 表

```sql
CREATE TABLE coverage_diffs (
    id BIGSERIAL PRIMARY KEY,
    base_coverage_run_id BIGINT NOT NULL,
    current_coverage_run_id BIGINT NOT NULL,

    line_coverage_delta NUMERIC(8,5),
    branch_coverage_delta NUMERIC(8,5),
    function_coverage_delta NUMERIC(8,5),

    new_lines BIGINT DEFAULT 0,
    covered_new_lines BIGINT DEFAULT 0,
    missed_new_lines BIGINT DEFAULT 0,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

# 27. Coverage Gate

配置：

```yaml
coverage_gate:
  line_min: 80
  branch_min: 70
  function_min: 80
  new_code_line_min: 85
```

检查：

```text
Line        82.6%   PASS
Branch      71.4%   PASS
Function    88.2%   PASS
New Code    72.1%   FAIL
```

最终：

```text
Coverage Gate = FAILED
```

CI 返回：

```text
exit code 1
```

从而阻断流水线。

---

# 28. Gate API

```http
GET /api/v1/coverage/runs/{run_id}/gate
```

返回：

```json
{
  "status": "FAILED",
  "rules": [
    {
      "name": "line",
      "actual": 82.6,
      "required": 80,
      "status": "PASS"
    },
    {
      "name": "new_code",
      "actual": 72.1,
      "required": 85,
      "status": "FAIL"
    }
  ]
}
```

---

# 29. Coverage Risk Engine

独立设计：

```text
Coverage Analysis Engine
```

输入：

```text
Coverage
+
Coverage Diff
+
Git Change
+
Test Result
+
Historical Bug
+
Business Criticality
```

输出：

```text
Risk Score
Risk Level
Risk Reason
Recommended Tests
```

第一版使用规则模型即可。

---

# 30. 风险评分

初始模型：

```text
Risk Score =
    0.30 × Coverage Risk
  + 0.25 × New Code Risk
  + 0.20 × Branch Risk
  + 0.15 × Historical Bug Risk
  + 0.10 × Change Size Risk
```

等级：

```text
0-30    LOW
31-60   MEDIUM
61-80   HIGH
81-100  CRITICAL
```

该权重不是最终科学模型，后续可以使用历史缺陷和测试结果进行校准。

---

# 31. Coverage 与测试用例关联

Test Run：

```text
Test Run ID = 3001
```

Coverage：

```text
Coverage Run
test_run_id = 3001
```

形成：

```text
Test Case
    ↓
Test Run
    ↓
Coverage Run
```

后续可以分析：

> 哪些测试用例对某段代码产生了覆盖？

---

# 32. Coverage 与 Git 关联

```text
Commit
 ↓
Build
 ↓
Test Run
 ↓
Coverage
```

Build 保存：

```text
repository
branch
commit_id
author
commit_message
```

从而可以计算：

```text
某次Commit导致Coverage下降多少？
```

---

# 33. Coverage 与 Bug 关联

未来：

```text
Bug
 ↓
affected_file
 ↓
affected_function
 ↓
Coverage
```

例如：

```text
BUG-1024

模块：
设备删除

文件：
device.py

函数：
delete_device()

历史Coverage：
42%
```

最终可以识别：

```text
低Coverage
+
高修改频率
+
历史Bug多
=
高风险区域
```

---

# 34. API 设计

## 上传

```http
POST /api/v1/coverage/upload
```

## 项目Summary

```http
GET /api/v1/projects/{project_id}/coverage/summary
```

## Build Coverage

```http
GET /api/v1/builds/{build_id}/coverage
```

## 文件列表

```http
GET /api/v1/coverage/runs/{run_id}/files
```

## 函数

```http
GET /api/v1/coverage/files/{file_id}/functions
```

## 行

```http
GET /api/v1/coverage/files/{file_id}/lines
```

## 趋势

```http
GET /api/v1/projects/{project_id}/coverage/trend
```

## Diff

```http
GET /api/v1/coverage/diff
```

## Gate

```http
GET /api/v1/coverage/runs/{run_id}/gate
```

## 任务

```http
GET /api/v1/tasks/{task_id}
```

---

# 35. 服务端真实实现示例

```python
@router.post("/coverage/upload")
async def upload_coverage(
    project_id: int,
    build_id: int,
    file: UploadFile,
):
    path = await storage.save(file)

    task = coverage_task.delay(
        project_id=project_id,
        build_id=build_id,
        path=path,
    )

    return {
        "task_id": task.id,
        "status": "PROCESSING",
    }
```

Worker：

```python
@celery.task
def coverage_task(project_id, build_id, path):

    parser = parser_factory.get_parser(path)

    report = parser.parse(path)

    run = coverage_service.create_run(
        project_id=project_id,
        build_id=build_id,
        report=report,
    )

    coverage_service.save_files(run, report)

    coverage_service.calculate_diff(run)

    coverage_service.check_gate(run)

    return run.id
```

---

# 36. 为什么使用异步任务

Coverage 报告可能很大。

如果：

```text
HTTP Upload
 ↓
直接解析100MB报告
 ↓
直接写数据库
```

HTTP 请求可能超时。

正确方式：

```text
Upload
 ↓
保存文件
 ↓
立即返回 task_id
 ↓
Celery Worker
 ↓
异步处理
```

---

# 37. 性能设计

Dashboard 不应该每次实时扫描：

```text
所有Line
+
所有Function
+
所有File
```

而应该在 Coverage 处理时计算：

```text
Project Summary
File Summary
Function Summary
```

Dashboard 直接查询 Summary。

---

# 38. 大数据量设计

如果项目达到百万级甚至千万级代码行：

不要无限期保存所有行明细在热数据库。

推荐：

```text
最近30~90天
完整明细 → PostgreSQL

历史数据
Summary → PostgreSQL

原始报告
→ MinIO
```

必要时：

```text
coverage_lines
coverage_branches
```

使用 PostgreSQL Partition。

---

# 39. 缓存

Redis 缓存：

```text
coverage:summary:{project_id}:{branch}
coverage:trend:{project_id}:{branch}
coverage:gate:{coverage_run_id}
```

Coverage 新数据产生时：

```text
删除旧缓存
```

---

# 40. 安全

必须：

- JWT/OAuth2 或企业统一认证
- 项目级权限
- Coverage 上传 Token
- 文件大小限制
- 文件类型检查
- 文件名清洗
- 路径穿越防护
- 原始报告访问鉴权
- 审计日志

不能仅靠前端控制项目权限。

---

# 41. 审计日志

记录：

```text
用户
项目
Build
Commit
Coverage Run
上传时间
工具
结果
错误
```

例如：

```text
USER-1001
上传 DevicePlatform
Build 1024
Commit abc123
Coverage 82.6%
```

---

# 42. 失败处理

阶段：

```text
UPLOAD
VALIDATE
PARSE
NORMALIZE
SAVE
DIFF
GATE
```

任何阶段失败：

```text
FAILED
```

错误：

```json
{
  "stage": "PARSE",
  "error_code": "INVALID_XML",
  "message": "coverage.xml format invalid"
}
```

允许人工重试。

---

# 43. 监控

建议：

```text
Prometheus
Grafana
```

指标：

```text
coverage_upload_total
coverage_parse_success_total
coverage_parse_failed_total
coverage_processing_duration
coverage_query_duration
coverage_gate_failed_total
```

日志建议 JSON 格式并带：

```text
trace_id
project_id
coverage_run_id
```

---

# 44. 测试设计

## Unit Test

覆盖：

```text
Parser
Calculation
Path Normalize
Diff
Gate
Risk
```

## Integration Test

```text
Upload
 ↓
Parser
 ↓
Database
 ↓
Query
```

## E2E

```text
创建Project
 ↓
创建Build
 ↓
执行pytest
 ↓
生成coverage.xml
 ↓
上传
 ↓
Coverage处理
 ↓
Dashboard
 ↓
Gate
```

---

# 45. Parser 单元测试

```python
def test_parse_python_coverage():

    report = parser.parse("coverage.xml")

    assert report.line_total == 100
    assert report.line_covered == 80
    assert report.line_rate == 0.8
```

异常：

```python
def test_invalid_report():

    with pytest.raises(ValueError):
        parser.parse("invalid.xml")
```

---

# 46. 数据一致性测试

必须验证：

```text
line_covered <= line_total
branch_covered <= branch_total
function_covered <= function_total
```

同时：

```text
rate = covered / total
```

特殊：

```text
total = 0
```

统一定义：

```text
rate = NULL
```

---

# 47. 第一阶段 MVP

必须实现：

```text
[√] Project
[√] Build
[√] Test Run
[√] Coverage Upload
[√] Python coverage.xml
[√] Parser
[√] Summary
[√] File Coverage
[√] Function Coverage
[√] Line Coverage
[√] Dashboard
[√] Trend
[√] Gate
[√] API
[√] CI 集成
```

暂不实现：

```text
[ ] 实时逐行Coverage
[ ] 多Agent
[ ] AI自动修改代码
[ ] 自动生成测试
[ ] Neo4j
[ ] 独立向量数据库
```

---

# 48. 第二阶段

增加：

```text
Java / JaCoCo
JavaScript / LCOV
C/C++ / llvm-cov
```

以及：

```text
Coverage Diff
New Code Coverage
Git Integration
```

---

# 49. 第三阶段

增加：

```text
Coverage Risk
Test Case Mapping
Bug Mapping
Coverage Hotspot
```

热点：

```text
低Coverage
+
高修改频率
+
历史Bug多
```

自动标记：

```text
HIGH RISK
```

---

# 50. 第四阶段：知识库与 AI

最终接入之前设计的知识库：

```text
Coverage
+
Git
+
Test Case
+
Bug
+
Knowledge
```

AI Orchestrator 查询：

```text
Coverage Service
Git Service
Test Service
Defect Service
Knowledge Service
```

例如用户问：

> 为什么本次覆盖率从82.6%下降到78.1%？

AI 获取：

```text
Coverage：
82.6% → 78.1%

Git：
新增device.py 200行

Coverage Diff：
新增未覆盖代码120行

Test：
没有对应异常场景

Knowledge：
设备删除测试规范要求覆盖4类异常
```

输出：

```text
本次Coverage下降4.5个百分点。

主要原因：
1. 新增代码覆盖不足
2. delete_device()异常分支未覆盖
3. 缺少对应测试场景
4. 该模块存在历史缺陷

建议增加：
- 删除不存在设备
- 删除在线设备
- 删除失败
- 删除超时
```

---

# 51. AI 测试生成闭环

最终：

```text
Code Commit
    ↓
Test
    ↓
Coverage
    ↓
Coverage Gap
    ↓
AI Analysis
    ↓
Knowledge Retrieval
    ↓
Test Case Generation
    ↓
人工审核
    ↓
Automation Script
    ↓
pytest / Playwright / ZMQ
    ↓
Test Execution
    ↓
Coverage
```

这才是测试平台长期建设方向。

---

# 52. 项目目录结构

```text
test-quality-platform/
│
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   │
│   │   ├── api/
│   │   │   ├── projects.py
│   │   │   ├── builds.py
│   │   │   ├── test_runs.py
│   │   │   └── coverage.py
│   │   │
│   │   ├── models/
│   │   │   ├── project.py
│   │   │   ├── build.py
│   │   │   ├── test_run.py
│   │   │   ├── coverage_run.py
│   │   │   ├── coverage_file.py
│   │   │   ├── coverage_line.py
│   │   │   ├── coverage_branch.py
│   │   │   └── coverage_function.py
│   │   │
│   │   ├── schemas/
│   │   │   └── coverage.py
│   │   │
│   │   ├── services/
│   │   │   ├── coverage_service.py
│   │   │   ├── diff_service.py
│   │   │   ├── gate_service.py
│   │   │   └── risk_service.py
│   │   │
│   │   ├── parsers/
│   │   │   ├── base.py
│   │   │   ├── coverage_xml.py
│   │   │   ├── jacoco.py
│   │   │   └── lcov.py
│   │   │
│   │   └── workers/
│   │       └── coverage_tasks.py
│   │
│   └── tests/
│
├── frontend/
│   └── src/
│       ├── views/
│       │   └── coverage/
│       ├── components/
│       └── api/
│
├── docker/
│   ├── postgres/
│   ├── redis/
│   └── minio/
│
└── docs/
```

---

# 53. 开发顺序

严格推荐：

```text
Step 1
Project + Build + Test Run

Step 2
Coverage Upload

Step 3
Python coverage.xml Parser

Step 4
统一 Coverage Model

Step 5
PostgreSQL

Step 6
Coverage Summary API

Step 7
File Coverage

Step 8
Function Coverage

Step 9
Line Coverage

Step 10
Vue Dashboard

Step 11
Trend

Step 12
Coverage Gate

Step 13
CI/CD

Step 14
Coverage Diff

Step 15
Git Integration

Step 16
Risk Engine

Step 17
Knowledge Integration

Step 18
AI Coverage Analysis
```

---

# 54. 第一条真实可运行链路

建议开发第一阶段只跑通：

```text
pytest
 ↓
coverage.xml
 ↓
POST /coverage/upload
 ↓
FastAPI
 ↓
Redis/Celery
 ↓
CoverageParser
 ↓
PostgreSQL
 ↓
GET /coverage/summary
 ↓
Vue Dashboard
```

成功后再加入：

```text
File
 ↓
Function
 ↓
Line
 ↓
Trend
 ↓
Gate
 ↓
Git Diff
 ↓
Risk
 ↓
Knowledge
 ↓
AI
```

---

# 55. MVP 验收标准

### 正常场景

上传有效 `coverage.xml`：

```text
处理成功
Coverage Run SUCCESS
Summary 正确
File 数据正确
Function 数据正确
Line 数据正确
```

### 重复上传

相同：

```text
Project
Build
Tool
File Hash
```

不能产生重复 Coverage。

### Coverage 下降

```text
82%
 ↓
75%
```

平台正确显示：

```text
-7个百分点
```

### New Code

```text
新增100行
覆盖60行
```

显示：

```text
New Code Coverage = 60%
```

### Gate

```text
要求80%
实际75%
```

返回：

```text
FAILED
exit code 1
```

### 非法报告

```text
INVALID_XML
FAILED
```

### 权限

项目无权限：

```text
403
```

---

# 56. 最终系统形态

```text
                         Test Quality Platform
                                  |
       +--------------------------+-------------------------+
       |                          |                         |
       v                          v                         v
 Test Management             Coverage System             Knowledge
       |                          |                         |
       |                          |                         |
 Test Case                    Collector                    RAG
 Test Run                     Parser                       Vector
 Defect                       Normalize                    SQL
       |                          |                       Relation
       +-------------+------------+----------------+---------+
                     |                             |
                     v                             v
                   Git                         AI Service
                     |                             |
                     +---------------+-------------+
                                     |
                                     v
                              Risk Analysis
                                     |
                                     v
                              Test Recommendation
                                     |
                                     v
                              Automation Engine
                                     |
                                     v
                                  Test Run
                                     |
                                     v
                                  Coverage
```

---

# 57. 最终设计原则

### 原则1：覆盖率工具不进入平台核心业务逻辑

通过 Parser Adapter 解耦。

### 原则2：原始报告与结构化数据分离

```text
MinIO → 原始报告
PostgreSQL → 查询数据
```

### 原则3：Coverage 明细与 Summary 分离

Dashboard 使用 Summary，源码详情使用明细。

### 原则4：同步 API 与异步计算分离

上传快速返回，解析后台执行。

### 原则5：全量 Coverage 与 New Code Coverage 同等重要

不能只看全量百分比。

### 原则6：Coverage 必须与 Commit、Build、Test Run 建立关系

否则无法真正做质量分析。

### 原则7：第一版不要过度微服务化

先模块化单体：

```text
FastAPI
+ PostgreSQL
+ Redis
+ Celery
+ MinIO
```

需要扩容时再拆。

---

# 58. 结论

该方案可以直接作为测试平台 Coverage 子系统的开发设计基线。

第一阶段采用：

```text
Python
FastAPI
PostgreSQL
Redis
Celery
MinIO
Vue3
pytest-cov
```

先实现：

```text
测试
 ↓
coverage.xml
 ↓
上传
 ↓
解析
 ↓
统一模型
 ↓
数据库
 ↓
Dashboard
 ↓
Gate
```

随后增加：

```text
Git
 ↓
Coverage Diff
 ↓
New Code Coverage
 ↓
Risk
 ↓
Knowledge
 ↓
AI
```

最终形成：

> **代码变更 → 测试执行 → Coverage → Coverage Gap → 风险识别 → 知识检索 → 测试建议 → 自动化执行 → Coverage 再验证**

这套闭环才是平台长期真正有价值的部分。
