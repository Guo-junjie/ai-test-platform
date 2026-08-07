# AI 自动化测试平台

> 100% 自闭环、无人工干预的 AI 自动化测试平台 — 从代码接入到测试报告全自动生成

## 项目简介

AI 自动化测试平台是一个企业级智能测试解决方案，通过 AI 模型自动完成代码解析、测试用例生成、多类型测试执行、缺陷智能分析和报告生成，实现从代码提交到测试报告的全链路自动化。

### 核心能力

- **多数据源接入**：GitHub / SVN / 手动上传，支持 Webhook 自动触发
- **AI 代码解析**：智能识别技术栈、自动提取 API 接口、语义分析业务逻辑
- **智能用例生成**：AI 自动生成正向/反向/边界/异常四类测试用例，覆盖率自动优化
- **三类测试并行**：接口测试 + 性能测试（Locust）+ 集成测试，Celery 异步并行执行
- **AI 缺陷分析**：自动识别缺陷类型与严重性（P0-P3），提供根因分析与修复建议
- **双模式报告**：交互式 HTML 在线报告 + PDF 导出报告，含可视化图表
- **企业级特性**：RBAC 权限、审计日志、质量门禁、多渠道通知告警、质量趋势看板

## 技术栈

### 后端

| 组件 | 技术选型 | 说明 |
|------|---------|------|
| Web 框架 | FastAPI 0.109 | 异步高性能 API 框架 |
| 任务调度 | Celery 5.3 + RabbitMQ | 异步任务队列，三类测试并行执行 |
| 数据库 | PostgreSQL 16 | 主数据存储，JSONB 存储灵活结构 |
| 缓存 | Redis 7 | 任务状态、缓存、检查点 |
| 对象存储 | MinIO | 代码快照、报告文件存储 |
| ORM | SQLAlchemy 2.0 (async) | 异步数据库操作 |
| 迁移 | Alembic 1.13 | 数据库版本管理 |
| AI 集成 | OpenAI / Anthropic / 自定义 | 统一模型客户端 + 智能路由 |
| 日志 | Loguru | 结构化日志，文件轮转 |

### 前端

| 组件 | 技术选型 | 说明 |
|------|---------|------|
| 框架 | Vue 3.4 + TypeScript | 组合式 API |
| UI 库 | Element Plus 2.5 | 企业级 UI 组件 |
| 状态管理 | Pinia 2.1 | 类型安全的状态管理 |
| 路由 | Vue Router 4.2 | 路由守卫 + 权限控制 |
| HTTP | Axios 1.6 | 请求/响应拦截器 |
| 图表 | ECharts 5.4 + vue-echarts | 可视化图表 |
| 构建 | Vite 5.0 | 快速 HMR 开发体验 |

### 基础设施

| 组件 | 版本 | 说明 |
|------|------|------|
| Docker | - | 全容器化部署 |
| Docker Compose | 3.8 | 8 个服务编排 |

## 快速启动

### 前置条件

- Docker 24.0+
- Docker Compose 2.20+
- Git

### 1. 克隆项目

```bash
git clone <repository-url>
cd ai-test-platform
```

### 2. 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env` 文件，按需修改以下关键配置：

```bash
# 必须修改：AI 模型 API Key
OPENAI_API_KEY=sk-your-openai-api-key
OPENAI_API_BASE=https://api.openai.com/v1
OPENAI_MODEL_NAME=gpt-4o

# 可选：备用模型
ANTHROPIC_API_KEY=your-anthropic-api-key

# 必须修改：加密密钥（生产环境，32 位以上随机字符串）
AES_ENCRYPTION_KEY=your-random-encryption-key-at-least-32-chars

# 必须修改：JWT 密钥
SECRET_KEY=your-jwt-secret-key

# 数据库（默认值可直接用于 Docker 环境）
POSTGRES_HOST=postgres
POSTGRES_PORT=5432
POSTGRES_USER=aitp
POSTGRES_PASSWORD=aitp_secret_2026
POSTGRES_DB=ai_test_platform

# Redis
REDIS_HOST=redis
REDIS_PORT=6379

# RabbitMQ
RABBITMQ_HOST=rabbitmq
RABBITMQ_PORT=5672
RABBITMQ_USER=aitp
RABBITMQ_PASSWORD=aitp_secret_2026

# MinIO
MINIO_ENDPOINT=minio:9000
MINIO_ACCESS_KEY=aitp
MINIO_SECRET_KEY=aitp_secret_2026
MINIO_BUCKET=ai-test-platform
```

### 3. 启动全部服务

```bash
docker-compose up -d
```

等待所有服务启动并完成健康检查（约 30 秒）：

```bash
# 查看服务状态
docker-compose ps

# 查看后端日志
docker-compose logs -f backend
```

### 4. 初始化数据库

首次启动时，FastAPI 的 lifespan 会自动执行 `init_db()` 创建表结构。

如需使用 Alembic 进行更精细的迁移管理：

```bash
# 进入后端容器执行迁移
docker-compose exec backend alembic upgrade head

# 查看当前迁移版本
docker-compose exec backend alembic current
```

### 5. 访问应用

| 服务 | 地址 | 说明 |
|------|------|------|
| 前端 | http://localhost:3000 | Vue 3 应用界面 |
| 后端 API | http://localhost:8000 | FastAPI 服务 |
| API 文档 | http://localhost:8000/docs | Swagger UI 自动文档 |
| MinIO 控制台 | http://localhost:9001 | 对象存储管理 |
| RabbitMQ 管理 | http://localhost:15672 | 消息队列监控 |

**默认 RabbitMQ 管理账号**：`aitp` / `aitp_secret_2026`
**默认 MinIO 控制台账号**：`aitp` / `aitp_secret_2026`

## 项目结构

```
ai-test-platform/
├── docker-compose.yml          # 全部服务编排（8 个服务）
├── .env.example                # 环境变量模板
├── README.md                   # 项目说明（本文件）
│
├── backend/                    # 后端服务
│   ├── Dockerfile              # 后端容器镜像
│   ├── requirements.txt        # Python 依赖
│   ├── alembic.ini             # Alembic 配置
│   ├── alembic/                # 数据库迁移
│   │   ├── env.py              # 迁移环境配置
│   │   ├── script.py.mako      # 迁移脚本模板
│   │   └── versions/
│   │       └── 001_initial.py  # 初始迁移（全部表）
│   └── app/
│       ├── main.py             # FastAPI 应用入口
│       ├── celery_app.py       # Celery 配置
│       ├── config.py           # Pydantic Settings 配置
│       ├── models/
│       │   └── database.py     # 全部数据库模型（10 张表）
│       ├── utils/
│       │   ├── database.py     # 异步数据库会话管理
│       │   ├── redis_client.py # Redis 客户端封装
│       │   ├── crypto.py       # AES-256 加密/解密
│       │   ├── logger.py       # Loguru 日志配置
│       │   └── storage.py      # MinIO 存储工具
│       ├── modules/
│       │   └── ai/
│       │       ├── model_config.py   # AI 模型配置数据结构
│       │       ├── model_client.py   # 统一模型客户端
│       │       └── model_router.py   # 模型路由器
│       └── api/                # API 路由
│           ├── source.py       # 数据源接入
│           ├── upload.py       # 文件上传
│           ├── webhook.py      # Webhook 接收
│           ├── model_config.py # AI 模型配置管理
│           ├── test_run.py     # 测试任务
│           ├── report.py       # 报告
│           ├── auth.py         # 认证
│           ├── settings.py     # 系统配置
│           └── audit.py        # 审计日志
│
└── frontend/                   # 前端服务
    ├── Dockerfile              # 前端容器镜像（Nginx）
    ├── nginx.conf              # Nginx 配置
    ├── package.json            # 前端依赖
    ├── vite.config.ts          # Vite 构建配置
    ├── tsconfig.json           # TypeScript 配置
    ├── index.html              # HTML 入口
    └── src/
        ├── main.ts             # Vue 应用入口
        ├── App.vue             # 根组件
        ├── router/index.ts     # 路由配置
        ├── api/index.ts        # Axios 实例封装
        ├── stores/index.ts     # Pinia Store 配置
        ├── components/
        │   └── Layout.vue      # 主布局组件
        └── views/              # 页面组件
            ├── Dashboard.vue
            ├── TestRun.vue
            ├── Report.vue
            ├── SourceManage.vue
            ├── Settings.vue
            ├── ModelConfig.vue
            ├── QualityGate.vue
            ├── AuditLog.vue
            └── QualityTrend.vue
```

## 开发指南

### 本地开发（非 Docker）

#### 后端

```bash
cd backend

# 创建虚拟环境
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 安装依赖
pip install -r requirements.txt

# 启动基础设施服务（仅 PostgreSQL/Redis/RabbitMQ/MinIO）
docker-compose up -d postgres redis rabbitmq minio

# 修改 .env 中的地址为 localhost
# POSTGRES_HOST=localhost
# REDIS_HOST=localhost
# ...

# 执行数据库迁移
alembic upgrade head

# 启动 FastAPI
uvicorn app.main:app --reload --port 8000

# 启动 Celery Worker（另一个终端）
celery -A app.celery_app worker --loglevel=info

# 启动 Celery Beat（另一个终端，定时任务）
celery -A app.celery_app beat --loglevel=info
```

#### 前端

```bash
cd frontend

# 安装依赖
npm install

# 启动开发服务器
npm run dev

# 构建生产版本
npm run build
```

### AI 模型配置

平台支持三种 AI 模型提供商：

1. **OpenAI 兼容**（默认）：支持 OpenAI / DeepSeek / vLLM / Ollama 等所有 OpenAI 兼容 API
2. **Anthropic Claude**：作为备用模型，主模型失败时自动切换
3. **自定义 HTTP API**：支持任意自定义 API 端点

配置方式：
- 环境变量：在 `.env` 文件中设置（首次启动自动初始化）
- 管理页面：启动后在前端「AI 模型配置」页面进行 CRUD 管理

### API 响应格式

所有 API 统一返回以下格式：

```json
{
  "code": 0,
  "data": {},
  "message": "success"
}
```

## 服务架构

```
                    ┌──────────────────────────────────────────┐
                    │              前端 (Vue 3)                 │
                    │         http://localhost:3000             │
                    └──────────────────┬───────────────────────┘
                                       │ HTTP / WebSocket
                    ┌──────────────────▼───────────────────────┐
                    │           后端 (FastAPI)                  │
                    │         http://localhost:8000             │
                    └──┬────────┬────────┬────────┬───────────┘
                       │        │        │        │
              ┌────────▼──┐ ┌───▼──┐ ┌───▼──┐ ┌───▼──────┐
              │ PostgreSQL │ │Redis │ │Rabbit│ │  MinIO   │
              │  (主数据)  │ │(缓存)│ │(MQ) │ │(对象存储)│
              └────────────┘ └──────┘ └──────┘ └──────────┘
                                       │
                    ┌──────────────────▼───────────────────────┐
                    │         Celery Worker × 3                 │
                    │  (source / analysis / execution / report) │
                    └──────────────────────────────────────────┘
```

## 许可证

私有项目，版权所有。
