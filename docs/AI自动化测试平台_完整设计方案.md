# AI 自动化测试平台 — 完整设计方案

> **定位**：100% 自闭环、无人工干预的 AI 自动化测试平台。支持三种代码数据源：① GitHub 仓库（公开/私有授权拉取，指定分支、Commit 或最新代码）；② SVN 仓库（账号授权拉取，指定修订版本或最新代码）；③ 人工上传代码文件（ZIP/TAR.GZ 压缩包直接上传）。实现代码接入后全自动完成：代码拉取/上传 → 架构解析 → 接口探测 → AI 测试用例生成 → 环境自动适配 → 全类型测试执行 → 缺陷自动捕获 → 结果校验 → 报告输出。

> **适配技术栈**：Java（Spring Boot）、Python（Flask/Django/FastAPI）、Go（Gin/Echo）、Node.js（Express/NestJS）、PHP（Laravel/ThinkPHP）等主流前后端项目。

---

## 一、平台整体架构图（文字版）+ 架构说明

### 1.1 分层架构

```
┌─────────────────────────────────────────────────────────────────────┐
│                        数据接入层 (Data Access)                       │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐                  │
│  │ GitHub 仓库  │  │  SVN 仓库   │  │ 人工上传文件  │                  │
│  │ OAuth/Token │  │ 账号/密码   │  │ ZIP/TAR.GZ  │                  │
│  │ 分支/Commit │  │ 修订版本    │  │ 拖拽/选择    │                  │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘                  │
│         └────────────────┼────────────────┘                          │
│                    统一代码接入网关                                     │
│         认证 → 拉取/接收 → 格式校验 → 代码快照存储                      │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────────┐
│                      智能解析层 (AI Analysis)                        │
│   技术栈识别 → 项目结构解析 → 接口定义提取 → 路由配置 → 依赖关系图     │
│   → 业务模块划分 → 变更点分析                                        │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────────┐
│                    用例生成层 (Case Generation)                      │
│   代码语义分析 → 业务场景建模 → 正向/反向/边界/异常用例 → 覆盖率优化  │
│   → 动态技术栈适配                                                   │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────────┐
│              测试执行层 (Test Execution Engine)                      │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐              │
│  │ 接口自动化测试 │  │ 性能自动化测试 │  │ 集成自动化测试 │              │
│  │ HTTP请求发送  │  │ 并发/阶梯压测  │  │ 全链路串联    │              │
│  │ 响应校验      │  │ TPS/QPS统计   │  │ 模块联动校验  │              │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘              │
│         └─────────────────┼─────────────────┘                       │
└───────────────────────────┼─────────────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────────────┐
│                    智能判定层 (Defect Intelligence)                  │
│   AI结果判定 → 缺陷分类(业务/程序/性能/集成) → 严重性分级(P0-P3)     │
│   → 成因分析 → 修复建议生成                                          │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────────┐
│                      报告输出层 (Report Output)                      │
│   数据汇总 → HTML/PDF生成 → 可视化图表 → 历史版本对比 → 存档          │
└─────────────────────────────────────────────────────────────────────┘

┌─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─┐
          容错监控层 (Fault Tolerance & Monitoring) — 贯穿全链路
   拉取失败重试 · 接口超时处理 · 环境异常兜底 · 任务中断恢复 · 健康检查
└─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─┘
```

### 1.2 架构说明

**设计原则**：

| 原则 | 说明 |
|------|------|
| **全自动化** | 从代码接入到报告输出，零人工介入。支持 GitHub/SVN 仓库 Webhook 自动触发，或手动指定仓库/上传文件即可启动全流程 |
| **AI 驱动** | 代码解析、用例生成、缺陷判定三个核心环节由 AI 模型驱动，非规则匹配 |
| **技术栈无关** | 通过适配器模式支持多技术栈，新增语言只需扩展解析器，不影响核心流程 |
| **并行执行** | 三类核心测试可并行调度，通过 Celery 分布式任务队列实现 |
| **容错自愈** | 每个环节均具备重试、超时、兜底机制，单点失败不阻断整体流程 |
| **可观测** | 全链路日志 + 实时进度追踪 + 历史版本对比 |

**核心数据流**：

```
数据源 (三选一)
  ├── GitHub Repo ──OAuth/Token──→ git clone/fetch
  ├── SVN Repo ─────账号/密码────→ svn checkout/export
  └── 人工上传 ─────────────────→ ZIP/TAR.GZ 解压
    │
    ▼
[代码接入模块] ──统一网关──→ 格式校验 → 代码快照存储(MinIO)
    │
    ▼
[AI代码解析模块] ──→ 技术栈报告 + 接口清单 + 依赖图 + 模块结构
    │                  (输出: analysis_result.json)
    ▼
[AI用例生成模块] ──→ 接口用例集 + 性能用例集 + 集成用例集
    │                  (输出: test_cases/*.json)
    ▼
[测试执行引擎] ──并行──→ 接口测试结果 + 性能测试结果 + 集成测试结果
    │                       (输出: test_results/*.json)
    ▼
[缺陷智能识别] ──→ 缺陷清单(分级) + 成因分析 + 修复建议
    │                  (输出: defects.json)
    ▼
[报告生成模块] ──→ 在线HTML报告(交互式) + PDF报告(导出) + 历史存档
                      (输出: reports/*.html, *.pdf)
```

### 1.3 模块间通信

- **同步调用**：代码拉取 → AI 解析 → 用例生成（串行依赖，前序输出是后序输入）
- **异步消息**：用例生成 → 测试执行（通过 Celery 队列分发，三类测试并行）
- **事件驱动**：各模块完成时发布事件，报告模块订阅汇总
- **状态共享**：Redis 存储任务状态、中间结果缓存；PostgreSQL 存储最终结果

---

## 二、全套技术选型

### 2.1 技术选型总览

| 层级 | 技术选型 | 选型理由 |
|------|---------|---------|
| **前端** | Vue 3 + TypeScript + Element Plus + ECharts | Vue 3 组合式 API 灵活，Element Plus 企业级组件库成熟，ECharts 可视化能力强 |
| **后端** | Python 3.12 + FastAPI | FastAPI 异步性能优异，原生支持 OpenAPI 文档，Python 生态对 AI/测试工具链支持最好 |
| **AI 模型** | 可配置多模型：默认 OpenAI GPT-4o + Anthropic Claude 3.5 Sonnet + 本地 CodeBERT；企业可自定义接入任意 OpenAI 兼容 API（含私有部署模型） | 支持运行时动态切换模型；CodeBERT 本地运行做快速代码特征提取，代码不出企业网络 |
| **测试引擎** | Pytest + HTTPx + Locust + 自研编排引擎 | Pytest 测试框架生态成熟；HTTPx 异步 HTTP 客户端高性能；Locust 分布式压测 |
| **任务调度** | Celery + RabbitMQ | Celery 分布式任务队列成熟稳定，RabbitMQ 消息可靠性高，支持任务优先级和重试 |
| **关系型存储** | PostgreSQL 16 | 存储：仓库配置、任务记录、测试结果、缺陷清单、报告元数据。JSONB 字段支持灵活结构 |
| **缓存/队列** | Redis 7 | 存储：任务状态、中间结果缓存、分布式锁、实时进度。内存数据库低延迟 |
| **对象存储** | MinIO（自建）/ S3（云） | 存储：代码快照、HTML/PDF报告、日志归档。兼容 S3 协议，可平滑迁移 |
| **容器化** | Docker + Docker Compose | 一键部署全部服务，环境隔离，支持按技术栈动态创建测试容器 |
| **CI/CD** | GitHub Actions（平台自身）| 平台自身更新部署，非用户项目 CI |

### 2.2 前端详细选型

```
Vue 3.4+           — 组合式 API，<script setup> 语法
TypeScript 5.3+    — 类型安全
Element Plus 2.5+  — UI 组件库（表格、表单、对话框、上传）
ECharts 5.4+       — 图表可视化（饼图、柱状图、折线图、桑基图）
Pinia 2.1+         — 状态管理
Vue Router 4.2+    — 路由管理
Axios 1.6+         — HTTP 请求
Day.js             — 时间处理
```

### 2.3 后端详细选型

```python
# 核心框架
fastapi==0.109.0        # Web 框架
uvicorn[standard]==0.27 # ASGI 服务器
pydantic==2.5.3         # 数据验证

# 任务调度
celery==5.3.6            # 分布式任务队列
kombu==5.3.4             # 消息传输抽象

# 数据库
sqlalchemy==2.0.25       # ORM
alembic==1.13.1          # 数据库迁移
psycopg2-binary==2.9.9   # PostgreSQL 驱动
redis==5.0.1             # Redis 客户端

# GitHub 集成
PyGithub==2.1.1          # GitHub API
gitpython==3.1.40        # Git 操作

# AI 集成（支持任意 OpenAI 兼容 API）
openai==1.6.1            # OpenAI 兼容客户端（通用于 GPT / 私有模型 / 国产模型）
anthropic==0.8.1         # Claude API（可选）
transformers==4.36.2     # 本地模型 (CodeBERT)
httpx==0.26.0            # 自定义 API 调用（非 OpenAI 兼容的模型）

# 测试引擎
pytest==7.4.4            # 测试框架
httpx==0.26.0            # 异步 HTTP 客户端
locust==2.20.0           # 性能压测
jsonschema==4.20.0       # JSON Schema 校验

# 报告生成
jinja2==3.1.2            # 模板引擎
weasyprint==60.2         # PDF 生成
matplotlib==3.8.2        # 图表生成（PDF内嵌）

# 容器管理
docker==7.0.0            # Docker SDK

# 工具库
loguru==0.7.2            # 日志
pyyaml==6.0.1            # YAML 解析
toml==0.10.2             # TOML 解析
```

### 2.4 AI 模型配置管理（企业级可配置）

#### 设计理念

企业对 AI 模型的需求各不相同：有的使用 OpenAI 官方 API，有的使用 Azure OpenAI，有的使用私有部署的 LLM（如 vLLM/Ollama 本地部署），有的使用国产模型（如通义千问、文心一言、DeepSeek）。平台采用**统一模型客户端 + 配置化管理**架构，支持运行时动态切换模型，无需修改代码。

#### 模型配置数据结构

```python
# modules/ai/model_config.py

from pydantic import BaseModel
from enum import Enum
from typing import Optional

class ModelProvider(Enum):
    OPENAI = "openai"           # OpenAI 官方 / 任何 OpenAI 兼容 API
    ANTHROPIC = "anthropic"     # Claude
    CUSTOM = "custom"           # 自定义 HTTP API（非 OpenAI 兼容格式）
    LOCAL = "local"             # 本地模型（CodeBERT 等）

class ModelConfig(BaseModel):
    """单个 AI 模型配置"""
    config_id: str               # 配置唯一标识
    name: str                    # 显示名称，如 "GPT-4o (公司代理)"
    provider: ModelProvider      # 提供商类型

    # API 地址（关键：企业可自定义）
    api_base_url: str            # API 基础地址，如 https://api.openai.com/v1
                                  # 或 https://internal-llm.company.com/v1
    api_key: str                  # API 密钥（AES-256 加密存储）
    model_name: str               # 模型名称，如 gpt-4o, claude-3-5-sonnet, deepseek-coder

    # 可选参数
    api_version: Optional[str] = None     # Azure OpenAI 需要 api-version
    max_tokens: int = 4096                 # 最大输出 token
    temperature: float = 0.3               # 温度参数
    timeout: int = 120                     # 请求超时（秒）
    max_retries: int = 3                   # 最大重试次数

    # 使用场景配置（该模型用于哪些环节）
    use_cases: list[str] = []   # ["code_analysis", "case_generation", "defect_analysis", "fix_suggestion"]

    # 状态
    is_active: bool = True      # 是否启用
    is_default: bool = False    # 是否为默认模型
    is_fallback: bool = False   # 是否为备用模型（主模型失败时切换）

class ModelRoutingConfig(BaseModel):
    """模型路由配置 — 按使用场景分配模型"""
    code_analysis_model_id: str       # 代码解析使用的模型配置 ID
    case_generation_model_id: str     # 用例生成
    defect_analysis_model_id: str     # 缺陷分析
    fix_suggestion_model_id: str      # 修复建议
    fallback_model_id: str            # 备用模型（任一主模型失败时切换）
```

#### 统一模型客户端

```python
# modules/ai/model_client.py

from openai import AsyncOpenAI
import httpx
import json
from loguru import logger

class UnifiedModelClient:
    """
    统一 AI 模型客户端

    支持任意 OpenAI 兼容 API（OpenAI 官方、Azure OpenAI、私有 vLLM/Ollama、
    国产模型 OpenAI 兼容接口等），也支持非兼容的自定义 HTTP API。
    """

    def __init__(self, config: ModelConfig):
        self.config = config
        self._client = None

        if config.provider == ModelProvider.OPENAI:
            # OpenAI 兼容 API（覆盖 90% 场景）
            self._client = AsyncOpenAI(
                api_key=config.api_key,
                base_url=config.api_base_url,
                timeout=config.timeout,
                max_retries=config.max_retries,
            )
        # Anthropic 和 Custom 在调用时按需处理

    async def chat(
        self,
        messages: list[dict],
        response_format_json: bool = False,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        """统一的对话接口"""
        temp = temperature if temperature is not None else self.config.temperature
        max_tok = max_tokens or self.config.max_tokens

        if self.config.provider == ModelProvider.OPENAI:
            kwargs = {
                "model": self.config.model_name,
                "messages": messages,
                "temperature": temp,
                "max_tokens": max_tok,
            }
            if response_format_json:
                kwargs["response_format"] = {"type": "json_object"}

            response = await self._client.chat.completions.create(**kwargs)
            return response.choices[0].message.content

        elif self.config.provider == ModelProvider.ANTHROPIC:
            # Anthropic Claude API
            return await self._call_anthropic(messages, temp, max_tok)

        elif self.config.provider == ModelProvider.CUSTOM:
            # 自定义 HTTP API（非 OpenAI 兼容格式）
            return await self._call_custom_api(messages, temp, max_tok)

    async def _call_anthropic(self, messages, temp, max_tok) -> str:
        """调用 Anthropic API"""
        async with httpx.AsyncClient(timeout=self.config.timeout) as client:
            # 提取 system message
            system_msg = ""
            user_messages = []
            for msg in messages:
                if msg["role"] == "system":
                    system_msg += msg["content"] + "\n"
                else:
                    user_messages.append(msg)

            response = await client.post(
                f"{self.config.api_base_url}/messages",
                headers={
                    "x-api-key": self.config.api_key,
                    "anthropic-version": self.config.api_version or "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": self.config.model_name,
                    "messages": user_messages,
                    "system": system_msg,
                    "max_tokens": max_tok,
                    "temperature": temp,
                },
            )
            response.raise_for_status()
            return response.json()["content"][0]["text"]

    async def _call_custom_api(self, messages, temp, max_tok) -> str:
        """调用自定义 API（适配企业内部模型服务）"""
        async with httpx.AsyncClient(timeout=self.config.timeout) as client:
            response = await client.post(
                f"{self.config.api_base_url}/chat",
                headers={
                    "Authorization": f"Bearer {self.config.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.config.model_name,
                    "messages": messages,
                    "temperature": temp,
                    "max_tokens": max_tok,
                },
            )
            response.raise_for_status()
            data = response.json()
            # 适配不同返回格式
            if "choices" in data:
                return data["choices"][0]["message"]["content"]
            elif "content" in data:
                return data["content"]
            else:
                return str(data)

    async def chat_json(self, messages: list[dict], **kwargs) -> dict:
        """调用模型并返回 JSON 对象"""
        content = await self.chat(messages, response_format_json=True, **kwargs)
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            # 尝试从 Markdown 代码块中提取 JSON
            import re
            json_match = re.search(r'```(?:json)?\s*([\s\S]*?)```', content)
            if json_match:
                return json.loads(json_match.group(1))
            raise ValueError(f"Model returned invalid JSON: {content[:200]}")
```

#### 模型路由器（按场景分配模型）

```python
# modules/ai/model_router.py

class ModelRouter:
    """
    模型路由器 — 根据使用场景选择对应的模型客户端

    企业可配置不同环节使用不同模型：
    - 代码解析: 用便宜的 GPT-4o-mini 或本地模型
    - 用例生成: 用最强的 GPT-4o
    - 缺陷分析: 用 Claude（长文本优势）
    """

    def __init__(self, routing_config: ModelRoutingConfig, model_configs: dict[str, ModelConfig]):
        self.routing = routing_config
        self.configs = model_configs
        self._clients: dict[str, UnifiedModelClient] = {}

    def get_client(self, use_case: str) -> UnifiedModelClient:
        """获取指定场景的模型客户端"""
        # 1. 根据场景查找配置 ID
        config_id_map = {
            "code_analysis": self.routing.code_analysis_model_id,
            "case_generation": self.routing.case_generation_model_id,
            "defect_analysis": self.routing.defect_analysis_model_id,
            "fix_suggestion": self.routing.fix_suggestion_model_id,
        }
        config_id = config_id_map.get(use_case)
        if not config_id:
            raise ValueError(f"Unknown use case: {use_case}")

        # 2. 获取模型配置
        config = self.configs.get(config_id)
        if not config or not config.is_active:
            # 3. 主模型不可用，切换到备用模型
            logger.warning(f"Model {config_id} not available, falling back")
            config = self.configs.get(self.routing.fallback_model_id)
            if not config:
                raise RuntimeError("No available model configuration")

        # 4. 创建或复用客户端实例
        if config_id not in self._clients:
            self._clients[config_id] = UnifiedModelClient(config)

        return self._clients[config_id]

    async def call(self, use_case: str, messages: list[dict], **kwargs) -> str:
        """统一调用入口 — 自动路由到对应模型"""
        client = self.get_client(use_case)
        try:
            return await client.chat(messages, **kwargs)
        except Exception as e:
            logger.error(f"Model call failed for {use_case}: {e}")
            # 切换到备用模型重试
            fallback_config = self.configs.get(self.routing.fallback_model_id)
            if fallback_config and fallback_config.is_active:
                logger.info(f"Retrying with fallback model: {fallback_config.name}")
                fallback_client = UnifiedModelClient(fallback_config)
                return await fallback_client.chat(messages, **kwargs)
            raise
```

#### 模型配置管理 API

```python
# api/model_config.py

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()

@router.get("/api/models/configs")
async def list_model_configs():
    """列出所有模型配置"""
    configs = await db.get_all_model_configs()
    # 隐藏 API Key
    for c in configs:
        c["api_key"] = "***" if c["api_key"] else None
    return configs

@router.post("/api/models/configs")
async def create_model_config(config: ModelConfig):
    """创建模型配置"""
    # 加密 API Key
    config.api_key = encrypt(config.api_key)
    await db.save_model_config(config)
    return {"status": "created", "config_id": config.config_id}

@router.put("/api/models/configs/{config_id}")
async def update_model_config(config_id: str, config: ModelConfig):
    """更新模型配置"""
    if config.api_key and config.api_key != "***":
        config.api_key = encrypt(config.api_key)
    else:
        # 不更新 API Key
        existing = await db.get_model_config(config_id)
        config.api_key = existing.api_key
    await db.update_model_config(config_id, config)
    return {"status": "updated"}

@router.post("/api/models/configs/{config_id}/test")
async def test_model_config(config_id: str):
    """测试模型连通性"""
    config = await db.get_model_config(config_id)
    config.api_key = decrypt(config.api_key)
    client = UnifiedModelClient(config)
    try:
        response = await client.chat([
            {"role": "user", "content": "Hello, respond with 'OK' if you receive this."}
        ], max_tokens=10)
        return {"status": "success", "response": response}
    except Exception as e:
        return {"status": "failed", "error": str(e)}

@router.put("/api/models/routing")
async def update_model_routing(routing: ModelRoutingConfig):
    """更新模型路由配置（配置各环节使用哪个模型）"""
    await db.save_model_routing(routing)
    return {"status": "updated"}
```

#### 常见企业模型配置示例

```python
# 示例配置：覆盖常见企业场景

EXAMPLE_CONFIGS = [
    # 1. OpenAI 官方
    ModelConfig(
        config_id="openai-gpt4o",
        name="OpenAI GPT-4o",
        provider=ModelProvider.OPENAI,
        api_base_url="https://api.openai.com/v1",
        api_key="sk-xxxxxxxx",
        model_name="gpt-4o",
    ),
    # 2. Azure OpenAI
    ModelConfig(
        config_id="azure-gpt4",
        name="Azure OpenAI GPT-4",
        provider=ModelProvider.OPENAI,
        api_base_url="https://your-resource.openai.azure.com/openai/deployments/gpt-4",
        api_key="your-azure-key",
        model_name="gpt-4",
        api_version="2024-02-15-preview",
    ),
    # 3. 私有部署 vLLM（运行 Llama/Qwen 等）
    ModelConfig(
        config_id="vllm-qwen",
        name="内部 Qwen-72B (vLLM)",
        provider=ModelProvider.OPENAI,  # vLLM 兼容 OpenAI API
        api_base_url="http://10.0.1.100:8000/v1",
        api_key="EMPTY",  # vLLM 默认不需要 key
        model_name="Qwen/Qwen2.5-72B-Instruct",
    ),
    # 4. DeepSeek
    ModelConfig(
        config_id="deepseek-coder",
        name="DeepSeek Coder",
        provider=ModelProvider.OPENAI,
        api_base_url="https://api.deepseek.com/v1",
        api_key="sk-xxxxxxxx",
        model_name="deepseek-coder",
    ),
    # 5. Ollama 本地部署
    ModelConfig(
        config_id="ollama-llama",
        name="Ollama Llama 3 (本地)",
        provider=ModelProvider.OPENAI,  # Ollama 兼容 OpenAI API
        api_base_url="http://localhost:11434/v1",
        api_key="ollama",
        model_name="llama3:70b",
    ),
    # 6. Anthropic Claude
    ModelConfig(
        config_id="claude-sonnet",
        name="Claude 3.5 Sonnet",
        provider=ModelProvider.ANTHROPIC,
        api_base_url="https://api.anthropic.com/v1",
        api_key="sk-ant-xxxxxxxx",
        model_name="claude-3-5-sonnet-20241022",
    ),
]
```

### 2.5 AI 模型分工（默认配置）

> 以下为出厂默认配置，企业可在「模型配置」页面修改为任意模型。

| 环节 | 默认模型 | 用途 | 调用方式 |
|------|------|------|---------|
| 代码解析 | GPT-4o | 理解项目结构、识别业务逻辑、提取接口语义 | 按接口粒度批量调用 |
| 用例生成 | GPT-4o | 基于代码语义生成测试用例 | 按接口粒度批量生成 |
| 缺陷判定 | Claude 3.5 Sonnet | 分析测试结果，判定缺陷类型和严重性 | 批量分析失败用例 |
| 代码特征提取 | CodeBERT (本地) | 快速提取代码嵌入向量，辅助接口分类 | 本地推理 |
| 修复建议 | GPT-4o | 基于缺陷上下文生成修复建议 | 按缺陷粒度生成 |

> **企业替换示例**：可将所有环节统一替换为私有部署的 Qwen-72B（通过 vLLM），代码不离开企业内网。

---

## 三、各核心模块详细设计方案与实现思路

### 3.1 代码接入模块（多数据源）

#### 职责
- 支持三种代码数据源统一接入：GitHub 仓库、SVN 仓库、人工上传文件
- 各数据源的认证与拉取/接收
- 代码格式校验与统一存储
- 增量更新（GitHub/SVN）与版本快照管理
- 失败重试机制

#### 数据源适配器架构

```python
# modules/source/base.py

from abc import ABC, abstractmethod
from pathlib import Path
from dataclasses import dataclass
from enum import Enum

class SourceType(Enum):
    GITHUB = "github"
    SVN = "svn"
    UPLOAD = "upload"

@dataclass
class SourceConfig:
    """统一数据源配置"""
    source_type: SourceType
    # GitHub 配置
    github_token: str | None = None
    repo_url: str | None = None
    branch: str = "main"
    commit_sha: str | None = None
    # SVN 配置
    svn_url: str | None = None
    svn_username: str | None = None
    svn_password: str | None = None
    svn_revision: str | None = None  # 指定修订版本，None 表示最新
    # 上传配置
    upload_file_path: str | None = None  # 上传的压缩包路径
    # 通用
    workspace_dir: str = "/data/repos"
    incremental: bool = True

class CodeSourceAdapter(ABC):
    """数据源适配器基类"""

    @abstractmethod
    def fetch(self, config: SourceConfig) -> dict:
        """拉取/接收代码，返回统一格式的结果"""
        ...

    @abstractmethod
    def supports_incremental(self) -> bool:
        """是否支持增量更新"""
        ...

class SourceAdapterFactory:
    """数据源适配器工厂"""

    _adapters = {}  # 运行时注册

    @classmethod
    def register(cls, source_type: SourceType, adapter_class):
        cls._adapters[source_type] = adapter_class

    @classmethod
    def get_adapter(cls, source_type: SourceType) -> CodeSourceAdapter:
        adapter = cls._adapters.get(source_type)
        if not adapter:
            raise ValueError(f"Unsupported source type: {source_type}")
        return adapter()

    @classmethod
    def fetch_code(cls, config: SourceConfig) -> dict:
        """统一入口：根据配置选择适配器拉取代码"""
        adapter = cls.get_adapter(config.source_type)
        result = adapter.fetch(config)

        # 统一后处理：创建版本快照
        snapshot_id = SnapshotManager.create(
            result["local_path"],
            result.get("version_id", "unknown")
        )
        result["snapshot_id"] = snapshot_id
        result["source_type"] = config.source_type.value
        return result
```

#### GitHub 适配器

```python
# modules/source/github_adapter.py

import git
from pathlib import Path
from datetime import datetime

class GitHubAdapter(CodeSourceAdapter):
    """GitHub 仓库数据源适配器"""

    def supports_incremental(self) -> bool:
        return True

    def fetch(self, config: SourceConfig) -> dict:
        repo_name = self._extract_repo_name(config.repo_url)
        local_path = Path(config.workspace_dir) / repo_name

        if local_path.exists() and config.incremental:
            return self._incremental_pull(config, local_path)
        else:
            return self._fresh_clone(config, local_path)

    def _fresh_clone(self, config: SourceConfig, local_path: Path) -> dict:
        authed_url = config.repo_url.replace(
            "https://github.com",
            f"https://{config.github_token}@github.com"
        )
        repo = git.Repo.clone_from(
            authed_url, str(local_path),
            branch=config.branch,
            depth=1 if not config.commit_sha else None,
        )
        if config.commit_sha:
            repo.git.checkout(config.commit_sha)

        return {
            "local_path": str(local_path),
            "version_id": repo.head.commit.hexsha,
            "version_label": f"branch={config.branch}, commit={repo.head.commit.hexsha[:8]}",
            "fetch_time": datetime.utcnow().isoformat() + "Z",
            "files_changed": [],
            "total_files": sum(1 for _ in local_path.rglob("*") if _.is_file()),
        }

    def _incremental_pull(self, config: SourceConfig, local_path: Path) -> dict:
        repo = git.Repo(str(local_path))
        old_sha = repo.head.commit.hexsha
        origin = repo.remotes.origin
        origin.fetch()

        if config.commit_sha:
            repo.git.checkout(config.commit_sha)
        else:
            repo.git.checkout(config.branch)
            origin.pull()

        new_sha = repo.head.commit.hexsha
        changed_files = []
        if old_sha != new_sha:
            diff = repo.git.diff("--name-only", old_sha, new_sha)
            changed_files = diff.split("\n") if diff else []

        return {
            "local_path": str(local_path),
            "version_id": new_sha,
            "version_label": f"branch={config.branch}, commit={new_sha[:8]}",
            "fetch_time": datetime.utcnow().isoformat() + "Z",
            "files_changed": changed_files,
            "total_files": sum(1 for _ in local_path.rglob("*") if _.is_file()),
        }

    def _extract_repo_name(self, repo_url: str) -> str:
        parts = repo_url.rstrip("/").split("/")
        return f"{parts[-2]}_{parts[-1]}"

# 注册适配器
SourceAdapterFactory.register(SourceType.GITHUB, GitHubAdapter)
```

#### SVN 适配器

```python
# modules/source/svn_adapter.py

import subprocess
import os
from pathlib import Path
from datetime import datetime

class SVNAdapter(CodeSourceAdapter):
    """SVN 仓库数据源适配器"""

    def supports_incremental(self) -> bool:
        return True

    def fetch(self, config: SourceConfig) -> dict:
        repo_name = self._extract_svn_name(config.svn_url)
        local_path = Path(config.workspace_dir) / repo_name

        if local_path.exists() and config.incremental:
            return self._svn_update(config, local_path)
        else:
            return self._svn_checkout(config, local_path)

    def _svn_checkout(self, config: SourceConfig, local_path: Path) -> dict:
        """SVN 全量检出"""
        cmd = ["svn", "checkout", config.svn_url, str(local_path)]

        # 认证参数
        if config.svn_username and config.svn_password:
            cmd.extend([
                "--username", config.svn_username,
                "--password", config.svn_password,
                "--non-interactive",
                "--no-auth-cache",
            ])

        # 指定修订版本
        if config.svn_revision:
            cmd.extend(["-r", config.svn_revision])

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if result.returncode != 0:
            raise RuntimeError(f"SVN checkout failed: {result.stderr}")

        # 获取当前修订版本号
        revision = self._get_revision(local_path)

        return {
            "local_path": str(local_path),
            "version_id": f"r{revision}",
            "version_label": f"svn_url={config.svn_url}, revision=r{revision}",
            "fetch_time": datetime.utcnow().isoformat() + "Z",
            "files_changed": [],
            "total_files": sum(1 for _ in local_path.rglob("*") if _.is_file()),
        }

    def _svn_update(self, config: SourceConfig, local_path: Path) -> dict:
        """SVN 增量更新"""
        # 获取更新前版本
        old_revision = self._get_revision(local_path)

        cmd = ["svn", "update", str(local_path)]
        if config.svn_username and config.svn_password:
            cmd.extend([
                "--username", config.svn_username,
                "--password", config.svn_password,
                "--non-interactive",
                "--no-auth-cache",
            ])
        if config.svn_revision:
            cmd.extend(["-r", config.svn_revision])

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if result.returncode != 0:
            raise RuntimeError(f"SVN update failed: {result.stderr}")

        new_revision = self._get_revision(local_path)

        # 获取变更文件列表
        changed_files = []
        if old_revision != new_revision:
            changed_files = self._get_changed_files(local_path, old_revision, new_revision)

        return {
            "local_path": str(local_path),
            "version_id": f"r{new_revision}",
            "version_label": f"svn_url={config.svn_url}, revision=r{new_revision}",
            "fetch_time": datetime.utcnow().isoformat() + "Z",
            "files_changed": changed_files,
            "total_files": sum(1 for _ in local_path.rglob("*") if _.is_file()),
        }

    def _get_revision(self, path: Path) -> str:
        """获取工作副本的修订版本号"""
        result = subprocess.run(
            ["svn", "info", "--show-item", "revision", str(path)],
            capture_output=True, text=True
        )
        return result.stdout.strip()

    def _get_changed_files(self, path: Path, old_rev: str, new_rev: str) -> list:
        """获取两个修订版本之间的变更文件"""
        result = subprocess.run(
            ["svn", "diff", "-r", f"{old_rev}:{new_rev}", "--summarize", str(path)],
            capture_output=True, text=True
        )
        files = []
        for line in result.stdout.strip().split("\n"):
            if line:
                # 格式: "M       path/to/file" / "A       path/to/file" / "D       path/to/file"
                parts = line.split(None, 1)
                if len(parts) == 2:
                    files.append(parts[1])
        return files

    def _extract_svn_name(self, svn_url: str) -> str:
        """从 SVN URL 提取项目名"""
        name = svn_url.rstrip("/").split("/")[-1]
        return f"svn_{name}"

# 注册适配器
SourceAdapterFactory.register(SourceType.SVN, SVNAdapter)
```

#### 人工上传适配器

```python
# modules/source/upload_adapter.py

import zipfile
import tarfile
import shutil
from pathlib import Path
from datetime import datetime
import hashlib

class UploadAdapter(CodeSourceAdapter):
    """人工上传代码文件适配器"""

    SUPPORTED_FORMATS = {".zip", ".tar.gz", ".tgz", ".tar"}

    def supports_incremental(self) -> bool:
        return False  # 上传模式不支持增量

    def fetch(self, config: SourceConfig) -> dict:
        upload_path = Path(config.upload_file_path)

        # 1. 格式校验
        if not upload_path.exists():
            raise FileNotFoundError(f"Upload file not found: {upload_path}")

        ext = self._get_extension(upload_path.name)
        if ext not in self.SUPPORTED_FORMATS:
            raise ValueError(f"Unsupported format: {ext}. Supported: {self.SUPPORTED_FORMATS}")

        # 2. 生成唯一目录名
        file_hash = hashlib.md5(upload_path.read_bytes()).hexdigest()[:8]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        project_name = upload_path.stem.replace(".tar", "")
        local_path = Path(config.workspace_dir) / f"upload_{project_name}_{timestamp}_{file_hash}"

        # 3. 解压
        local_path.mkdir(parents=True, exist_ok=True)

        if ext == ".zip":
            with zipfile.ZipFile(upload_path, 'r') as zf:
                # 安全检查：防止 zip slip 攻击
                for member in zf.namelist():
                    member_path = (local_path / member).resolve()
                    if not str(member_path).startswith(str(local_path.resolve())):
                        raise ValueError(f"Unsafe zip entry: {member}")
                zf.extractall(local_path)
        elif ext in (".tar.gz", ".tgz"):
            with tarfile.open(upload_path, 'r:gz') as tf:
                self._safe_extract(tf, local_path)
        elif ext == ".tar":
            with tarfile.open(upload_path, 'r:') as tf:
                self._safe_extract(tf, local_path)

        # 4. 检查是否有一层多余包装目录（如 repo-name/ 下才是源码）
        local_path = self._flatten_if_needed(local_path)

        # 5. 清理上传的临时文件
        upload_path.unlink(missing_ok=True)

        return {
            "local_path": str(local_path),
            "version_id": file_hash,
            "version_label": f"upload: {upload_path.name} (md5={file_hash})",
            "fetch_time": datetime.utcnow().isoformat() + "Z",
            "files_changed": [],
            "total_files": sum(1 for _ in local_path.rglob("*") if _.is_file()),
        }

    def _safe_extract(self, tar: tarfile.TarFile, path: Path):
        """安全解压 tar 文件，防止路径穿越"""
        for member in tar.getmembers():
            member_path = (path / member.name).resolve()
            if not str(member_path).startswith(str(path.resolve())):
                raise ValueError(f"Unsafe tar entry: {member.name}")
        tar.extractall(path)

    def _flatten_if_needed(self, path: Path) -> Path:
        """如果解压后只有一个子目录，则将其内容提升到当前目录"""
        children = [c for c in path.iterdir() if not c.name.startswith(".")]
        if len(children) == 1 and children[0].is_dir():
            sole_dir = children[0]
            for item in sole_dir.iterdir():
                shutil.move(str(item), str(path / item.name))
            sole_dir.rmdir()
        return path

    def _get_extension(self, filename: str) -> str:
        lower = filename.lower()
        for ext in [".tar.gz", ".tgz", ".zip", ".tar"]:
            if lower.endswith(ext):
                return ext
        return Path(lower).suffix

# 注册适配器
SourceAdapterFactory.register(SourceType.UPLOAD, UploadAdapter)
```

#### 上传接收 API

```python
# api/upload.py

from fastapi import APIRouter, UploadFile, File, HTTPException
from pathlib import Path

router = APIRouter()
UPLOAD_DIR = Path("/data/uploads")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

MAX_UPLOAD_SIZE = 500 * 1024 * 1024  # 500MB

@router.post("/api/source/upload")
async def upload_code(file: UploadFile = File(...)):
    """接收人工上传的代码压缩包"""
    # 校验文件类型
    filename = file.filename
    valid_extensions = (".zip", ".tar.gz", ".tgz", ".tar")
    if not filename.lower().endswith(valid_extensions):
        raise HTTPException(400, f"Unsupported format. Supported: {valid_extensions}")

    # 保存文件
    save_path = UPLOAD_DIR / filename
    total_size = 0
    with open(save_path, "wb") as f:
        while chunk := await file.read(1024 * 1024):  # 1MB chunks
            total_size += len(chunk)
            if total_size > MAX_UPLOAD_SIZE:
                save_path.unlink(missing_ok=True)
                raise HTTPException(413, f"File too large. Max: {MAX_UPLOAD_SIZE // 1024 // 1024}MB")
            f.write(chunk)

    # 触发测试流程
    config = SourceConfig(
        source_type=SourceType.UPLOAD,
        upload_file_path=str(save_path),
    )
    result = SourceAdapterFactory.fetch_code(config)

    return {
        "status": "accepted",
        "local_path": result["local_path"],
        "snapshot_id": result["snapshot_id"],
        "total_files": result["total_files"],
    }
```

#### 重试机制

```python
import time
from functools import wraps

def retry_with_backoff(max_retries=3, base_delay=2, max_delay=30):
    """指数退避重试装饰器"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except (git.exc.GitCommandError, subprocess.CalledProcessError,
                        ConnectionError, TimeoutError) as e:
                    last_exception = e
                    if attempt < max_retries - 1:
                        delay = min(base_delay * (2 ** attempt), max_delay)
                        time.sleep(delay)
            raise last_exception
        return wrapper
    return decorator
```

### 3.2 AI 代码解析模块

#### 职责
- 智能识别技术栈（语言+框架）
- 解析项目结构
- 提取全部 API 接口定义
- 解析路由配置
- 分析模块依赖关系
- 划分业务模块

#### 技术栈识别策略

```python
# modules/code_analyzer/stack_detector.py

STACK_SIGNATURES = {
    "java_spring": {
        "files": ["pom.xml", "build.gradle"],
        "framework_files": ["src/main/resources/application.yml", "src/main/resources/application.properties"],
        "annotations": ["@RestController", "@RequestMapping", "@GetMapping", "@PostMapping"],
        "language": "java",
        "framework": "spring-boot",
    },
    "python_flask": {
        "files": ["requirements.txt", "setup.py", "pyproject.toml"],
        "framework_imports": ["from flask import", "import flask"],
        "route_decorators": ["@app.route", "@blueprint.route", "@bp.route"],
        "language": "python",
        "framework": "flask",
    },
    "python_django": {
        "files": ["manage.py", "requirements.txt"],
        "framework_files": ["settings.py"],
        "framework_imports": ["from django", "import django"],
        "language": "python",
        "framework": "django",
    },
    "python_fastapi": {
        "files": ["requirements.txt", "pyproject.toml"],
        "framework_imports": ["from fastapi import", "import fastapi"],
        "route_decorators": ["@app.get", "@app.post", "@router.get", "@router.post"],
        "language": "python",
        "framework": "fastapi",
    },
    "go_gin": {
        "files": ["go.mod"],
        "framework_imports": ['"github.com/gin-gonic/gin"'],
        "route_patterns": ["r.GET(", "r.POST(", "router.GET(", "router.POST("],
        "language": "go",
        "framework": "gin",
    },
    "node_express": {
        "files": ["package.json"],
        "framework_files": ["node_modules/express"],
        "route_patterns": ["app.get(", "app.post(", "router.get(", "router.post("],
        "language": "javascript",
        "framework": "express",
    },
    "node_nestjs": {
        "files": ["package.json"],
        "framework_files": ["nest-cli.json"],
        "annotations": ["@Controller(", "@Get(", "@Post(", "@Put(", "@Delete("],
        "language": "typescript",
        "framework": "nestjs",
    },
    "php_laravel": {
        "files": ["composer.json"],
        "framework_files": ["artisan", "config/app.php"],
        "route_files": ["routes/api.php", "routes/web.php"],
        "language": "php",
        "framework": "laravel",
    },
}

class StackDetector:
    def detect(self, project_path: str) -> dict:
        """识别项目技术栈"""
        path = Path(project_path)
        detected = []

        for stack_name, signature in STACK_SIGNATURES.items():
            score = self._calculate_score(path, signature)
            if score > 0.5:
                detected.append({
                    "stack": stack_name,
                    "language": signature["language"],
                    "framework": signature["framework"],
                    "confidence": score,
                })

        # 取置信度最高的
        best = max(detected, key=lambda x: x["confidence"]) if detected else None
        return best
```

#### 接口提取（以 Spring Boot 为例）

```python
# modules/code_analyzer/api_extractor.py

import re
from pathlib import Path
from typing import List

class SpringAPIExtractor:
    """Spring Boot 接口提取器"""

    # 匹配 @RequestMapping / @GetMapping / @PostMapping 等
    ROUTE_PATTERN = re.compile(
        r'@(?:Request|Get|Post|Put|Delete|Patch)Mapping\s*\('
        r'(?:value\s*=\s*)?"([^"]+)"'
        r'(?:.*?method\s*=\s*RequestMethod\.(\w+))?'
        r'[^)]*\)',
        re.DOTALL
    )

    # 匹配方法签名
    METHOD_PATTERN = re.compile(
        r'(?:public\s+)?(\w+(?:<[^>]+>)?)\s+(\w+)\s*\(([^)]*)\)',
        re.DOTALL
    )

    # 匹配 @RequestBody, @PathVariable, @RequestParam
    PARAM_PATTERNS = {
        "request_body": re.compile(r'@RequestBody\s+(\w+(?:<[^>]+>)?)\s+(\w+)'),
        "path_variable": re.compile(r'@PathVariable(?:\s*\(\s*"([^"]+)"\s*\))?\s+(\w+(?:<[^>]+>)?)\s+(\w+)'),
        "request_param": re.compile(r'@RequestParam(?:\s*\(\s*"([^"]+)"\s*\))?(?:\s*(required\s*=\s*(true|false)))?\s+(\w+(?:<[^>]+>)?)\s+(\w+)'),
        "request_header": re.compile(r'@RequestHeader(?:\s*\(\s*"([^"]+)"\s*\))?\s+(\w+(?:<[^>]+>)?)\s+(\w+)'),
    }

    def extract(self, project_path: str) -> List[dict]:
        """提取所有 API 接口"""
        controllers = self._find_controllers(project_path)
        apis = []

        for controller_file in controllers:
            class_routes = self._get_class_level_routes(controller_file)
            methods = self._parse_controller_methods(controller_file)

            for method in methods:
                api = self._build_api_def(method, class_routes, controller_file)
                if api:
                    apis.append(api)

        return apis

    def _find_controllers(self, project_path: str) -> List[Path]:
        """查找所有 Controller 文件"""
        controllers = []
        for ext in ["*.java", "*.kt"]:
            for f in Path(project_path).rglob(ext):
                content = f.read_text(encoding="utf-8", errors="ignore")
                if "@RestController" in content or "@Controller" in content:
                    controllers.append(f)
        return controllers

    def _parse_controller_methods(self, file_path: Path) -> List[dict]:
        """解析 Controller 中的接口方法"""
        content = file_path.read_text(encoding="utf-8", errors="ignore")
        methods = []

        for match in self.ROUTE_PATTERN.finditer(content):
            route_path = match.group(1)
            http_method = match.group(2) or self._infer_method_from_annotation(match.group(0))

            # 在注解之后查找方法签名
            after_annotation = content[match.end():match.end() + 500]
            method_match = self.METHOD_PATTERN.search(after_annotation)

            if method_match:
                return_type = method_match.group(1)
                method_name = method_match.group(2)
                params_str = method_match.group(3)

                params = self._parse_params(params_str)

                methods.append({
                    "path": route_path,
                    "http_method": http_method,
                    "return_type": return_type,
                    "method_name": method_name,
                    "params": params,
                    "file": str(file_path),
                    "line_number": content[:match.start()].count("\n") + 1,
                })

        return methods

    def _parse_params(self, params_str: str) -> list:
        """解析方法参数"""
        params = []
        for param_type, pattern in self.PARAM_PATTERNS.items():
            for match in pattern.finditer(params_str):
                if param_type == "request_body":
                    params.append({
                        "type": "body",
                        "data_type": match.group(1),
                        "name": match.group(2),
                        "required": True,
                    })
                elif param_type == "path_variable":
                    name = match.group(1) or match.group(3)
                    params.append({
                        "type": "path",
                        "data_type": match.group(2),
                        "name": name,
                        "required": True,
                    })
                elif param_type == "request_param":
                    name = match.group(1) or match.group(5)
                    required = match.group(2) != "false" if match.group(2) else True
                    params.append({
                        "type": "query",
                        "data_type": match.group(4),
                        "name": name,
                        "required": required,
                    })
                elif param_type == "request_header":
                    name = match.group(1) or match.group(3)
                    params.append({
                        "type": "header",
                        "data_type": match.group(2),
                        "name": name,
                        "required": True,
                    })
        return params
```

#### AI 语义分析增强

```python
# modules/code_analyzer/ai_analyzer.py

class AICodeAnalyzer:
    """使用 LLM 进行深度代码语义分析"""

    def __init__(self, model_router: ModelRouter):
        self.router = model_router

    async def analyze_business_logic(self, code_content: str, api_info: dict) -> dict:
        """
        AI 分析接口的业务逻辑

        Returns:
            {
                "business_purpose": "用户注册接口，验证手机号和邮箱后创建账户",
                "key_validations": ["手机号格式校验", "邮箱唯一性校验", "密码强度校验"],
                "business_rules": ["同一手机号24小时内只能注册3次", "注册成功后发送欢迎邮件"],
                "expected_responses": {
                    "success": {"code": 200, "body": {"userId": "string", "token": "string"}},
                    "failure": {"code": 400, "body": {"error": "string", "code": "int"}}
                },
                "dependencies": ["UserService.create", "SmsService.sendCode", "MailService.sendWelcome"],
                "risk_points": ["未验证邮箱所有权", "密码明文传输风险"]
            }
        """
        prompt = f"""
        分析以下 API 接口的业务逻辑:

        接口信息:
        - 路径: {api_info['path']}
        - 方法: {api_info['http_method']}
        - 参数: {json.dumps(api_info['params'], ensure_ascii=False)}

        代码:
        ```
        {code_content}
        ```

        请输出 JSON 格式的分析结果，包含:
        1. business_purpose: 业务用途描述
        2. key_validations: 关键校验逻辑列表
        3. business_rules: 业务规则列表
        4. expected_responses: 预期响应格式 (成功/失败)
        5. dependencies: 依赖的服务/模块列表
        6. risk_points: 潜在风险点
        """

        return await self.router.call_json(
            use_case="code_analysis",
            messages=[{"role": "user", "content": prompt}],
        )
```

### 3.3 AI 用例生成模块

#### 职责
- 基于代码语义与业务场景生成高覆盖率测试用例
- 生成正向、反向、边界值、异常参数用例
- 动态适配不同技术栈和项目特征

#### 用例生成策略

```python
# modules/case_generator/case_generator.py

class TestCaseGenerator:
    """AI 测试用例生成器"""

    def __init__(self, model_router: ModelRouter):
        self.router = model_router

    async def generate_api_cases(self, api_info: dict, business_analysis: dict) -> dict:
        """
        为单个 API 生成全套测试用例

        Returns:
            {
                "api_path": "/api/v1/users",
                "method": "POST",
                "cases": [
                    {
                        "case_id": "TC_001",
                        "case_type": "positive",
                        "case_name": "正常创建用户",
                        "request": {
                            "method": "POST",
                            "url": "/api/v1/users",
                            "headers": {"Content-Type": "application/json", "Authorization": "Bearer {{token}}"},
                            "body": {"username": "testuser_001", "email": "test@example.com", "phone": "13800138000", "password": "Test@1234"}
                        },
                        "expected": {
                            "status_code": 200,
                            "response_schema": {"code": "integer", "data": {"userId": "string", "token": "string"}},
                            "assertions": [
                                {"type": "status_code", "expected": 200},
                                {"type": "json_path", "path": "$.code", "expected": 0},
                                {"type": "json_path", "path": "$.data.userId", "operator": "not_null"},
                                {"type": "json_path", "path": "$.data.token", "operator": "not_null"}
                            ]
                        },
                        "priority": "P0"
                    },
                    // ... 更多用例
                ]
            }
        """
        prompt = self._build_generation_prompt(api_info, business_analysis)

        cases = await self.router.call_json(
            use_case="case_generation",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,  # 低温度保证用例稳定性
        )

        # 后处理：补充用例ID、优先级
        for i, case in enumerate(cases["cases"]):
            case["case_id"] = f"TC_{i+1:03d}"
            case.setdefault("priority", self._infer_priority(case["case_type"]))

        return cases

    def _build_generation_prompt(self, api_info: dict, analysis: dict) -> str:
        return f"""
        你是资深测试工程师。根据以下接口信息生成完整的自动化测试用例。

        ## 接口信息
        - 路径: {api_info['path']}
        - 方法: {api_info['http_method']}
        - 参数定义: {json.dumps(api_info['params'], ensure_ascii=False, indent=2)}

        ## 业务分析
        {json.dumps(analysis, ensure_ascii=False, indent=2)}

        ## 生成要求
        生成以下类型的测试用例:

        ### 1. 正向用例 (positive) - 至少 3 个
        - 覆盖正常业务流程的所有合法参数组合
        - 包含不同合法值的边界场景

        ### 2. 反向用例 (negative) - 至少 5 个
        - 必填参数缺失（逐个缺失 + 全部缺失）
        - 参数类型错误（字符串传数字、数字传字符串等）
        - 参数格式非法（邮箱格式、手机号格式等）
        - 业务规则违反（重复注册、越权操作等）
        - 认证/授权缺失或无效

        ### 3. 边界值用例 (boundary) - 至少 4 个
        - 字符串长度边界（空串、最小长度、最大长度、超长）
        - 数值边界（最小值、最大值、0、负数、超大数）
        - 集合大小边界（空数组、单元素、最大容量）

        ### 4. 异常用例 (exception) - 至少 3 个
        - 请求体格式错误（非法 JSON、缺少 Content-Type）
        - 超大请求体
        - SQL 注入尝试
        - XSS 载荷
        - 特殊字符和 Unicode

        ## 输出格式
        JSON，包含 cases 数组，每个用例包含:
        - case_type: positive/negative/boundary/exception
        - case_name: 用例名称（中文）
        - request: {method, url, headers, body, params}
        - expected: {status_code, assertions: [{type, path, expected/operator}]}
        - description: 用例说明

        URL 中的路径参数用实际值替换，查询参数放在 params 中。
        变量（如 token）用 {{{{variable}}}} 格式表示。
        """

    def _infer_priority(self, case_type: str) -> str:
        priority_map = {
            "positive": "P0",
            "negative": "P1",
            "boundary": "P1",
            "exception": "P2",
        }
        return priority_map.get(case_type, "P2")
```

#### 覆盖率优化

```python
class CoverageOptimizer:
    """测试覆盖率优化器"""

    def optimize(self, cases: list, code_paths: list) -> list:
        """
        分析已有用例的代码路径覆盖率，补充未覆盖路径的用例

        Args:
            cases: 已生成的用例列表
            code_paths: 代码中所有执行路径（从 AST 分析获得）

        Returns:
            补充后的用例列表
        """
        covered_paths = set()
        for case in cases:
            covered_paths.update(case.get("covered_paths", []))

        uncovered = [p for p in code_paths if p not in covered_paths]

        if not uncovered:
            return cases

        # 为未覆盖路径生成补充用例
        supplement_prompt = self._build_supplement_prompt(uncovered)
        # ... LLM 生成补充用例 ...

        return cases + supplement_cases
```

### 3.4 测试执行引擎

#### 职责
- 统一调度三类核心测试
- 自动适配运行环境
- 动态调参
- 并行执行

#### 调度架构

```python
# modules/execution/engine.py

from celery import Celery, group, chain
from enum import Enum

app = Celery("test_platform", broker="amqp://rabbitmq", backend="redis://redis")

class TestType(Enum):
    API = "api"
    PERFORMANCE = "performance"
    INTEGRATION = "integration"

class TestExecutionEngine:
    """测试执行引擎 - 统一调度三类测试"""

    def execute_all(self, test_run_id: str, analysis_result: dict, test_cases: dict) -> str:
        """
        调度全部测试任务

        流程:
        1. 环境准备（启动被测服务容器）
        2. 三类测试并行执行
        3. 结果汇总
        """
        # Step 1: 环境准备
        env_task = prepare_environment.s(test_run_id, analysis_result)

        # Step 2: 三类测试并行
        test_tasks = group(
            run_api_tests.s(test_run_id, test_cases["api"]),
            run_performance_tests.s(test_run_id, test_cases["performance"], analysis_result),
            run_integration_tests.s(test_run_id, test_cases["integration"], analysis_result),
        )

        # Step 3: 结果汇总
        aggregate_task = aggregate_results.s(test_run_id)

        # 串联执行
        workflow = chain(env_task, test_tasks, aggregate_task)
        result = workflow.apply_async()

        return result.id


@app.task(bind=True, max_retries=3, default_retry_delay=30)
def prepare_environment(self, test_run_id: str, analysis_result: dict) -> dict:
    """准备测试环境 - 根据技术栈启动被测服务"""
    stack = analysis_result["tech_stack"]
    repo_path = analysis_result["local_path"]

    try:
        # 根据技术栈选择环境适配器
        adapter = EnvironmentAdapterFactory.get_adapter(stack)
        service_url = adapter.start_service(repo_path)

        # 等待服务就绪
        adapter.wait_for_ready(service_url, timeout=120)

        return {"test_run_id": test_run_id, "service_url": service_url, "status": "ready"}
    except Exception as exc:
        raise self.retry(exc=exc)


@app.task(bind=True, max_retries=2)
def run_api_tests(self, test_run_id: str, api_cases: list) -> dict:
    """执行接口测试"""
    # ... 详见 5.1 节 ...
    pass


@app.task(bind=True, max_retries=1)
def run_performance_tests(self, test_run_id: str, perf_cases: list, analysis: dict) -> dict:
    """执行性能测试"""
    # ... 详见 5.2 节 ...
    pass


@app.task(bind=True, max_retries=2)
def run_integration_tests(self, test_run_id: str, integration_cases: list, analysis: dict) -> dict:
    """执行集成测试"""
    # ... 详见 5.3 节 ...
    pass
```

#### 环境适配器

```python
# modules/execution/env_adapters.py

class EnvironmentAdapter:
    """环境适配器基类"""
    def start_service(self, repo_path: str) -> str:
        raise NotImplementedError

    def wait_for_ready(self, url: str, timeout: int = 120):
        import httpx
        import time
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                r = httpx.get(f"{url}/health", timeout=5)
                if r.status_code < 500:
                    return
            except:
                pass
            time.sleep(3)
        raise TimeoutError(f"Service not ready within {timeout}s")

class JavaSpringAdapter(EnvironmentAdapter):
    def start_service(self, repo_path: str) -> str:
        """启动 Spring Boot 服务"""
        import docker
        client = docker.from_env()

        # 构建 Docker 镜像
        image_tag = f"test-target:{hash(repo_path)}"
        client.images.build(path=repo_path, tag=image_tag, dockerfile="Dockerfile")

        # 运行容器
        container = client.containers.run(
            image_tag,
            ports={"8080/tcp": None},  # 随机端口
            environment={"SPRING_PROFILES_ACTIVE": "test"},
            detach=True,
        )

        # 获取映射端口
        port = container.ports["8080/tcp"][0]["HostPort"]
        return f"http://localhost:{port}"

class PythonFastAPIAdapter(EnvironmentAdapter):
    def start_service(self, repo_path: str) -> str:
        """启动 FastAPI 服务"""
        import docker
        client = docker.from_env()

        image_tag = f"test-target:{hash(repo_path)}"
        client.images.build(path=repo_path, tag=image_tag)

        container = client.containers.run(
            image_tag,
            ports={"8000/tcp": None},
            environment={"ENV": "test"},
            detach=True,
        )

        port = container.ports["8000/tcp"][0]["HostPort"]
        return f"http://localhost:{port}"

class EnvironmentAdapterFactory:
    ADAPTERS = {
        "java_spring": JavaSpringAdapter,
        "python_flask": PythonFlaskAdapter,
        "python_fastapi": PythonFastAPIAdapter,
        "python_django": PythonDjangoAdapter,
        "go_gin": GoGinAdapter,
        "node_express": NodeExpressAdapter,
        "node_nestjs": NodeNestJSAdapter,
        "php_laravel": PhpLaravelAdapter,
    }

    @classmethod
    def get_adapter(cls, stack: str) -> EnvironmentAdapter:
        adapter_class = cls.ADAPTERS.get(stack)
        if not adapter_class:
            raise ValueError(f"Unsupported tech stack: {stack}")
        return adapter_class()
```

### 3.5 缺陷智能识别模块

#### 职责
- AI 判定测试结果
- 区分业务异常/程序 BUG/性能问题/集成兼容问题
- 自动分级（P0-P3）
- 成因分析
- 修复建议生成

```python
# modules/defect_analyzer/analyzer.py

class DefectAnalyzer:
    """缺陷智能识别模块"""

    def __init__(self, model_router: ModelRouter):
        self.router = model_router

    DEFECT_CATEGORIES = {
        "business_exception": {
            "description": "业务逻辑异常 - 接口返回了预期的错误码",
            "severity_base": "P3",
        },
        "program_bug": {
            "description": "程序 BUG - 接口返回 500 或响应结构与预期不符",
            "severity_base": "P1",
        },
        "performance_issue": {
            "description": "性能问题 - 响应时间过长或吞吐量不达标",
            "severity_base": "P2",
        },
        "integration_failure": {
            "description": "集成故障 - 模块间数据传递失败或流程断裂",
            "severity_base": "P1",
        },
        "security_vulnerability": {
            "description": "安全漏洞 - 接口越权、参数注入等安全问题",
            "severity_base": "P0",
        },
    }

    SEVERITY_RULES = {
        "P0": "阻断性问题：服务崩溃、数据泄露、安全漏洞",
        "P1": "严重问题：核心功能不可用、接口报错",
        "P2": "一般问题：性能不达标、边界场景异常",
        "P3": "轻微问题：非核心功能异常、优化建议",
    }

    def analyze(self, test_results: dict) -> dict:
        """分析全部测试结果，识别缺陷"""
        defects = []

        # 分析接口测试失败
        for result in test_results.get("api_results", []):
            if not result["passed"]:
                defect = self._analyze_api_failure(result)
                defects.append(defect)

        # 分析性能测试
        for result in test_results.get("performance_results", []):
            defect = self._analyze_performance(result)
            if defect:
                defects.append(defect)

        # 分析集成测试
        for result in test_results.get("integration_results", []):
            if not result["passed"]:
                defect = self._analyze_integration_failure(result)
                defects.append(defect)

        # AI 去重和合并
        defects = self._deduplicate(defects)

        return {
            "total_defects": len(defects),
            "by_severity": self._group_by_severity(defects),
            "by_category": self._group_by_category(defects),
            "defects": defects,
        }

    def _analyze_api_failure(self, result: dict) -> dict:
        """使用 AI 分析接口测试失败"""
        prompt = f"""
        分析以下接口测试失败，判定缺陷类型和严重性。

        ## 测试用例
        - 用例名称: {result['case_name']}
        - 用例类型: {result['case_type']}
        - 请求: {json.dumps(result['request'], ensure_ascii=False)}
        - 预期: {json.dumps(result['expected'], ensure_ascii=False)}
        - 实际响应:
          - 状态码: {result['actual_status_code']}
          - 响应体: {result['actual_response']}

        ## 判定要求
        1. category: 从以下选择 - business_exception / program_bug / security_vulnerability
        2. severity: P0(阻断) / P1(严重) / P2(一般) / P3(轻微)
        3. root_cause: 根因分析（中文，2-3句话）
        4. fix_suggestion: 修复建议（中文，具体可操作）
        5. reproduction_steps: 复现步骤

        输出 JSON 格式。
        """

        # 使用 AI 分析（通过模型路由器自动选择配置的模型）
        defect = await self.router.call_json(
            use_case="defect_analysis",
            messages=[{"role": "user", "content": prompt}],
        )
        return defect
```

### 3.6 报告生成模块

#### 职责
- 实时汇总数据
- 生成可视化图表与结构化报告
- **在线交互式报告**：在平台内直接打开浏览，支持交互筛选、图表缩放、用例详情展开/折叠
- **PDF 导出报告**：一键导出 PDF，适合存档和分享
- 支持存档与历史版本对比

```python
# modules/report/generator.py

from jinja2 import Environment, FileSystemLoader
import json
from datetime import datetime

class ReportGenerator:
    """报告生成模块 — 支持在线查看 + PDF 导出"""

    def __init__(self, template_dir: str = "templates"):
        self.env = Environment(loader=FileSystemLoader(template_dir))

    async def generate(self, test_run_id: str, all_results: dict) -> dict:
        """
        生成报告 — 同时产出在线 HTML 和 PDF 两种格式

        - 在线 HTML：包含 ECharts 交互式图表，可在平台内直接打开浏览
        - PDF：从 HTML 渲染导出，适合存档和分享

        Returns:
            {
                "online_url": "https://platform/reports/{test_run_id}",  # 在线访问地址
                "html_path": "reports/{test_run_id}/report.html",
                "pdf_path": "reports/{test_run_id}/report.pdf",
                "summary": {...}
            }
        """
        # 1. 数据汇总
        summary = self._build_summary(all_results)

        # 2. 生成可视化数据
        charts_data = self._build_chart_data(all_results)

        # 3. 渲染在线 HTML（含 ECharts 交互式图表）
        template = self.env.get_template("report_interactive.html")
        html_content = template.render(
            summary=summary,
            charts=charts_data,
            details=all_results,
            generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            test_run_id=test_run_id,
            # 在线模式标记（HTML 中包含交互 JS）
            mode="online",
        )

        html_path = f"reports/{test_run_id}/report.html"
        self._save(html_path, html_content)

        # 4. 生成 PDF（从 HTML 导出，静态图表替代交互图表）
        pdf_html = self._render_pdf_version(summary, charts_data, all_results, test_run_id)
        pdf_path = f"reports/{test_run_id}/report.pdf"
        self._html_to_pdf(pdf_html, pdf_path)

        # 5. 上传到对象存储
        online_url = self._upload_to_storage(html_path, pdf_path, test_run_id)

        return {
            "online_url": online_url,
            "html_path": html_path,
            "pdf_path": pdf_path,
            "summary": summary,
        }

    def _render_pdf_version(self, summary, charts_data, details, test_run_id):
        """渲染 PDF 专用的 HTML（静态图表替代交互图表）"""
        template = self.env.get_template("report_pdf.html")
        return template.render(
            summary=summary,
            charts=charts_data,  # PDF 模板使用 matplotlib 静态图片
            details=details,
            generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            test_run_id=test_run_id,
            mode="pdf",
        )

    def _build_summary(self, results: dict) -> dict:
        """构建报告摘要"""
        api = results.get("api_results", {})
        perf = results.get("performance_results", {})
        integ = results.get("integration_results", {})
        defects = results.get("defects", {})

        return {
            "basic_info": results["basic_info"],
            "quality_score": self._calculate_quality_score(api, perf, integ, defects),
            "overall_pass": defects.get("P0", 0) == 0 and defects.get("P1", 0) == 0,
            "api_summary": {
                "total_cases": api.get("total", 0),
                "passed": api.get("passed", 0),
                "failed": api.get("failed", 0),
                "pass_rate": f"{api.get('passed', 0) / max(api.get('total', 1), 1) * 100:.1f}%",
            },
            "performance_summary": {
                "tested_apis": perf.get("total_apis", 0),
                "avg_response_time": f"{perf.get('avg_rt', 0):.0f}ms",
                "avg_tps": f"{perf.get('avg_tps', 0):.1f}",
                "bottleneck_apis": perf.get("bottlenecks", []),
            },
            "integration_summary": {
                "total_chains": integ.get("total", 0),
                "passed": integ.get("passed", 0),
                "pass_rate": f"{integ.get('passed', 0) / max(integ.get('total', 1), 1) * 100:.1f}%",
            },
            "defect_summary": {
                "total": defects.get("total", 0),
                "by_severity": {
                    "P0": defects.get("P0", 0),
                    "P1": defects.get("P1", 0),
                    "P2": defects.get("P2", 0),
                    "P3": defects.get("P3", 0),
                },
            },
        }

    def _calculate_quality_score(self, api, perf, integ, defects) -> int:
        """计算质量评分 (0-100)"""
        score = 100

        # API 测试通过率扣分
        api_pass_rate = api.get("passed", 0) / max(api.get("total", 1), 1)
        score -= (1 - api_pass_rate) * 40

        # 性能问题扣分
        if perf.get("bottlenecks"):
            score -= len(perf["bottlenecks"]) * 5

        # 集成测试失败扣分
        integ_pass_rate = integ.get("passed", 0) / max(integ.get("total", 1), 1)
        score -= (1 - integ_pass_rate) * 30

        # 缺陷扣分
        score -= defects.get("P0", 0) * 15
        score -= defects.get("P1", 0) * 8
        score -= defects.get("P2", 0) * 3
        score -= defects.get("P3", 0) * 1

        return max(0, min(100, int(score)))
```

### 3.7 容错监控模块

#### 职责
- 处理拉取失败、接口超时、环境异常、任务中断
- 自动重试与兜底机制
- 全链路健康监控

```python
# modules/monitor/fault_tolerance.py

from enum import Enum
from dataclasses import dataclass

class FaultType(Enum):
    PULL_FAILURE = "pull_failure"
    SVN_AUTH_FAILURE = "svn_auth_failure"
    UPLOAD_CORRUPTED = "upload_corrupted"
    API_TIMEOUT = "api_timeout"
    ENV_EXCEPTION = "env_exception"
    TASK_INTERRUPT = "task_interrupt"
    AI_RATE_LIMIT = "ai_rate_limit"
    DISK_FULL = "disk_full"

@dataclass
class FaultHandler:
    """容错处理器"""

    handlers = {
        FaultType.PULL_FAILURE: {
            "max_retries": 3,
            "backoff_base": 5,
            "backoff_max": 60,
            "fallback": "use_cached_snapshot",
        },
        FaultType.API_TIMEOUT: {
            "max_retries": 2,
            "backoff_base": 2,
            "backoff_max": 15,
            "fallback": "mark_as_timeout",
        },
        FaultType.ENV_EXCEPTION: {
            "max_retries": 3,
            "backoff_base": 10,
            "backoff_max": 120,
            "fallback": "use_default_env",
        },
        FaultType.TASK_INTERRUPT: {
            "max_retries": 1,
            "backoff_base": 30,
            "backoff_max": 30,
            "fallback": "resume_from_checkpoint",
        },
        FaultType.AI_RATE_LIMIT: {
            "max_retries": 5,
            "backoff_base": 30,
            "backoff_max": 300,
            "fallback": "switch_to_backup_model",
        },
    }

    @classmethod
    def handle(cls, fault_type: FaultType, context: dict) -> dict:
        """处理故障"""
        config = cls.handlers[fault_type]

        for attempt in range(config["max_retries"]):
            try:
                # 尝试恢复
                result = cls._attempt_recovery(fault_type, context, attempt)
                return {"status": "recovered", "attempt": attempt + 1, "result": result}
            except Exception as e:
                delay = min(config["backoff_base"] * (2 ** attempt), config["backoff_max"])
                time.sleep(delay)

        # 所有重试失败，执行兜底策略
        fallback_result = cls._execute_fallback(config["fallback"], context)
        return {"status": "fallback", "strategy": config["fallback"], "result": fallback_result}

    @classmethod
    def _execute_fallback(cls, strategy: str, context: dict) -> dict:
        """执行兜底策略"""
        if strategy == "use_cached_snapshot":
            # 使用上次成功的代码快照
            return {"snapshot_id": context.get("last_snapshot_id")}

        elif strategy == "mark_as_timeout":
            # 标记接口为超时
            return {"status": "timeout", "api": context.get("api_path")}

        elif strategy == "use_default_env":
            # 使用默认测试环境
            return {"env": "default", "url": "http://default-test-env:8080"}

        elif strategy == "resume_from_checkpoint":
            # 从检查点恢复
            checkpoint = context.get("checkpoint")
            return {"resumed_from": checkpoint}

        elif strategy == "switch_to_backup_model":
            # 切换到备用 AI 模型（由 ModelRouter 自动处理）
            return {"model": "fallback_model (由模型路由器配置决定)"}
```

---

## 四、多数据源对接完整流程与授权配置方案

### 4.1 数据源总览

平台支持三种代码数据源，统一接入后进入相同的测试流程：

| 数据源 | 认证方式 | 版本指定 | 增量更新 | 自动触发 | 适用场景 |
|-------|---------|---------|---------|---------|---------|
| **GitHub 仓库** | OAuth App / Personal Token / GitHub App | 分支 / Commit SHA | ✅ git fetch+pull | ✅ Webhook | 开源项目、Git 工作流团队 |
| **SVN 仓库** | 账号/密码 | 修订版本号 | ✅ svn update | ✅ Post-commit Hook | 传统企业、遗留系统 |
| **人工上传** | 无（平台用户身份） | 文件 MD5 | ❌ 每次全量 | ❌ 手动触发 | 外部代码、无仓库权限、快速验证 |

### 4.2 GitHub 授权配置

#### 方式一：GitHub OAuth App（推荐）

```
1. 在 GitHub 创建 OAuth App
   - Settings → Developer settings → OAuth Apps → New OAuth App
   - Application name: AI Test Platform
   - Homepage URL: https://your-platform-domain
   - Authorization callback URL: https://your-platform-domain/auth/callback

2. 获取 Client ID 和 Client Secret

3. 请求用户授权
   GET https://github.com/login/oauth/authorize?
       client_id={CLIENT_ID}&
       scope=repo,read:org,workflow&
       redirect_uri={CALLBACK_URL}

4. 获取 Access Token
   POST https://github.com/login/oauth/access_token
   {
       "client_id": "{CLIENT_ID}",
       "client_secret": "{CLIENT_SECRET}",
       "code": "{AUTH_CODE}"
   }

5. 使用 Token 访问 GitHub API
   Authorization: token {ACCESS_TOKEN}
```

#### 方式二：Personal Access Token（简化模式）

```
1. 用户在 GitHub 生成 Personal Access Token
   - Settings → Developer settings → Personal access tokens → Fine-grained tokens
   - Repository access: 选择目标仓库
   - Permissions: Contents (Read), Metadata (Read)

2. 在平台配置页面输入 Token
```

#### 方式三：GitHub App（企业级）

```
1. 创建 GitHub App
   - Settings → Developer settings → GitHub Apps → New GitHub App
   - 配置 Webhook URL: https://your-platform-domain/webhook/github
   - Permissions:
     * Contents: Read-only
     * Metadata: Read-only
     * Pull requests: Read-only
     * Commit statuses: Read-only

2. 安装 App 到目标仓库/组织

3. 使用 App Private Key 生成 Installation Token
```

### 4.2 完整拉取流程

```
用户操作                        平台内部处理
────────                        ────────────
[连接GitHub账号] ──→ OAuth授权流程 ──→ 获取Access Token ──→ 加密存储
                                                                       
[选择仓库] ────→ 调用 GitHub API    ──→ 获取仓库列表
                   GET /user/repos      返回: 仓库列表 JSON
                                                                       
[选择分支/Commit] ──→ 调用 GitHub API  ──→ 获取分支和 Commit 列表
                       GET /repos/{owner}/{repo}/branches
                       GET /repos/{owner}/{repo}/commits
                                                                       
[启动测试] ────→ 创建测试任务 ──────→ 任务入队 (Celery)
                                                                       
                ┌──────────────────────────────────────────┐
                │  Task: pull_repository                    │
                │  1. 克隆/拉取代码到 /data/repos/{name}    │
                │  2. 记录 Commit SHA                       │
                │  3. 创建版本快照 → MinIO                  │
                │  4. 计算变更文件列表                      │
                │  5. 发送事件: code.pulled                 │
                └──────────────────────────────────────────┘
```

### 4.3 增量更新机制

```python
def incremental_update(repo_path: str, branch: str) -> dict:
    """
    增量更新流程:
    1. git fetch origin {branch}
    2. 比较本地 HEAD 与远端 HEAD
    3. 若有变更: git pull origin {branch}
    4. 通过 git diff 计算变更文件列表
    5. 仅对变更文件相关的接口重新解析和测试
    """
    repo = git.Repo(repo_path)
    old_sha = repo.head.commit.hexsha

    origin = repo.remotes.origin
    origin.fetch(branch)

    remote_sha = repo.refs[f"origin/{branch}"].commit.hexsha

    if old_sha == remote_sha:
        return {"changed": False, "files": []}

    # 获取变更文件
    diff = repo.git.diff("--name-only", old_sha, remote_sha)
    changed_files = diff.split("\n") if diff else []

    # 拉取变更
    origin.pull(branch)

    # 智能过滤：只测试受变更影响的接口
    affected_apis = analyze_file_impact(changed_files, repo_path)

    return {
        "changed": True,
        "old_sha": old_sha,
        "new_sha": remote_sha,
        "files": changed_files,
        "affected_apis": affected_apis,
    }
```

### 4.4 Webhook 自动触发

```python
# api/webhook.py

from fastapi import APIRouter, Request, HTTPException
import hmac, hashlib

router = APIRouter()

WEBHOOK_SECRET = "your_webhook_secret"

@router.post("/webhook/github")
async def github_webhook(request: Request):
    """GitHub Webhook 处理 - 代码推送自动触发测试"""
    # 1. 验证签名
    body = await request.body()
    signature = request.headers.get("X-Hub-Signature-256", "")
    expected = "sha256=" + hmac.new(
        WEBHOOK_SECRET.encode(), body, hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(signature, expected):
        raise HTTPException(status_code=401, detail="Invalid signature")

    # 2. 解析事件
    event = request.headers.get("X-GitHub-Event", "")
    payload = await request.json()

    if event == "push":
        # 代码推送事件
        repo_url = payload["repository"]["clone_url"]
        branch = payload["ref"].replace("refs/heads/", "")
        commit_sha = payload["after"]

        # 3. 创建测试任务
        test_run = await create_test_run(
            repo_url=repo_url,
            branch=branch,
            commit_sha=commit_sha,
            trigger="webhook",
        )

        return {"status": "accepted", "test_run_id": test_run.id}

    return {"status": "ignored"}
```

### 4.5 SVN 仓库对接流程

#### SVN 认证配置

```
1. 在平台「数据源管理」页面选择「添加 SVN 仓库」
2. 填写配置:
   - SVN 仓库 URL: https://svn.company.com/svn/project-name/trunk
   - 用户名: svn_username
   - 密码: svn_password（加密存储，AES-256）
   - 可选：指定修订版本号（留空则拉取最新）

3. 平台验证连接:
   - 执行 svn info --username xxx --password xxx --non-interactive URL
   - 验证通过后保存配置
```

#### SVN 拉取流程

```
用户操作                         平台内部处理
────────                        ────────────
[添加SVN仓库] ──→ 认证校验 ──→ 加密存储凭据

[选择版本] ────→ 调用 svn info    ──→ 获取最新修订版本号
                 可选指定历史版本

[启动测试] ────→ 创建测试任务 ──→ 任务入队 (Celery)

                ┌──────────────────────────────────────────┐
                │  Task: svn_fetch                          │
                │  1. svn checkout/update 到 /data/repos/  │
                │  2. 记录修订版本号                         │
                │  3. 创建版本快照 → MinIO                   │
                │  4. 计算变更文件列表(svn diff --summarize) │
                │  5. 发送事件: code.pulled                  │
                └──────────────────────────────────────────┘
```

#### SVN Post-commit Hook 自动触发

```python
# api/webhook.py — SVN post-commit hook 接收端

@router.post("/webhook/svn")
async def svn_post_commit_hook(request: Request):
    """SVN post-commit 钩子回调

    SVN 仓库的 post-commit 脚本配置:
    # 在 SVN 服务器仓库的 hooks/post-commit 文件中:
    #!/bin/sh
    REPOS="$1"
    REV="$2"
    curl -X POST https://your-platform-domain/webhook/svn \
      -H "Content-Type: application/json" \
      -d "{\"repos\": \"$REPOS\", \"revision\": \"$REV\"}"
    """
    payload = await request.json()
    repos = payload.get("repos", "")
    revision = payload.get("revision", "")

    # 根据 repos URL 匹配已配置的 SVN 仓库
    svn_config = await find_svn_config_by_url(repos)
    if not svn_config:
        return {"status": "ignored", "reason": "no matching svn config"}

    # 创建测试任务
    test_run = await create_test_run(
        source_type="svn",
        svn_url=svn_config["svn_url"],
        svn_revision=revision,
        trigger="svn_hook",
    )

    return {"status": "accepted", "test_run_id": test_run.id}
```

### 4.6 人工上传对接流程

```
用户操作                         平台内部处理
────────                        ────────────
[选择上传文件] ──→ 拖拽或选择     ──→ ZIP/TAR.GZ 文件
                                      ↓
[上传] ──────→ 分块接收(1MB)    ──→ 大小校验(≤500MB)
                                      ↓
                ┌──────────────────────────────────────────┐
                │  Task: upload_process                     │
                │  1. 格式校验 (zip/tar.gz/tar)             │
                │  2. 安全检查 (防 zip slip / 路径穿越)      │
                │  3. 解压到 /data/repos/upload_xxx/        │
                │  4. 目录扁平化 (去掉多余包装层)            │
                │  5. 记录文件 MD5 作为版本标识              │
                │  6. 创建版本快照 → MinIO                   │
                │  7. 发送事件: code.pulled                  │
                └──────────────────────────────────────────┘
                                      ↓
[自动进入测试流程] ──→ 解析 → 生成用例 → 执行 → 报告
```

### 4.7 统一数据源选择 API

```python
# api/source.py

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()

class SourceRequest(BaseModel):
    source_type: str  # "github" | "svn" | "upload"
    # GitHub
    repo_url: str | None = None
    branch: str = "main"
    commit_sha: str | None = None
    # SVN
    svn_url: str | None = None
    svn_revision: str | None = None
    # Upload (上传后返回的 file_id)
    upload_file_id: str | None = None
    # 通用
    test_types: list[str] = ["api", "performance", "integration"]
    auto_trigger: bool = True

@router.post("/api/source/fetch")
async def fetch_source(req: SourceRequest):
    """统一数据源接入入口"""
    config = build_source_config(req)
    result = SourceAdapterFactory.fetch_code(config)

    # 自动触发测试
    if req.auto_trigger:
        test_run = await create_test_run(
            source_type=req.source_type,
            local_path=result["local_path"],
            version_id=result["version_id"],
            test_types=req.test_types,
        )
        return {
            "fetch_result": result,
            "test_run_id": test_run.id,
        }

    return {"fetch_result": result}
```

---

## 五、三类核心测试的全自动执行逻辑细节

### 5.1 接口自动化测试

#### 执行流程

```
接口用例列表
    │
    ├─ 按优先级排序 (P0 → P1 → P2 → P3)
    │
    ├─ 依赖分析 (提取用例间的前置依赖关系)
    │   例: "登录接口" 必须先于 "获取用户信息接口" 执行
    │
    ├─ 变量准备
    │   - 注册测试账号 (用于需要认证的接口)
    │   - 生成测试数据 (唯一用户名、邮箱等)
    │
    ├─ 并行执行 (同一优先级内并行，跨优先级串行)
    │   ┌─────────────────────────────────────────────┐
    │   │ Worker 1: 执行 TC_001 (正常注册)            │
    │   │ Worker 2: 执行 TC_005 (邮箱格式错误)        │
    │   │ Worker 3: 执行 TC_012 (密码边界值)          │
    │   │ Worker 4: 执行 TC_018 (SQL注入尝试)         │
    │   └─────────────────────────────────────────────┘
    │
    ├─ 响应校验
    │   - 状态码校验: actual == expected
    │   - 响应结构校验: JSON Schema 匹配
    │   - 字段值校验: jsonpath 断言
    │   - 业务逻辑校验: AI 判定返回数据是否符合业务预期
    │   - 响应时间记录: 用于性能参考
    │
    ├─ 错误捕获
    │   - HTTP 错误 (4xx, 5xx)
    │   - 超时 (响应时间 > 阈值)
    │   - 连接错误 (服务不可达)
    │   - 响应结构异常 (JSON 解析失败)
    │   - 业务逻辑错误 (返回成功但数据不符合预期)
    │
    └─ 结果输出
        {
            "case_id": "TC_001",
            "passed": true/false,
            "actual_status_code": 200,
            "actual_response": {...},
            "response_time_ms": 45,
            "error_type": "assertion_failed" / "timeout" / "connection_error",
            "error_detail": "Expected status 200, got 500. Response: {\"error\":\"NPE\"}",
            "assertions": [
                {"type": "status_code", "passed": true, "expected": 200, "actual": 200},
                {"type": "json_path", "path": "$.code", "passed": false, "expected": 0, "actual": 1}
            ]
        }
```

#### 核心执行代码

```python
# modules/execution/api_tester.py

import httpx
import asyncio
import json
from datetime import datetime

class APITestRunner:
    """接口测试执行器"""

    def __init__(self, base_url: str, timeout: int = 30):
        self.base_url = base_url
        self.timeout = timeout
        self.variable_store = {}  # 存储用例间共享的变量

    async def run_cases(self, cases: list) -> list:
        """执行全部接口测试用例"""
        # 1. 按优先级分组
        priority_groups = self._group_by_priority(cases)

        # 2. 依赖排序
        ordered_cases = self._topological_sort(cases)

        # 3. 同优先级内并行执行
        results = []
        for priority in ["P0", "P1", "P2", "P3"]:
            group = [c for c in ordered_cases if c["priority"] == priority]
            if not group:
                continue

            batch_results = await asyncio.gather(*[
                self._run_single_case(case) for case in group
            ])
            results.extend(batch_results)

        return results

    async def _run_single_case(self, case: dict) -> dict:
        """执行单个测试用例"""
        # 1. 准备请求 (替换变量)
        request = self._prepare_request(case["request"])

        # 2. 发送请求
        start_time = datetime.now()
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.request(
                    method=request["method"],
                    url=self.base_url + request["url"],
                    headers=request.get("headers", {}),
                    json=request.get("body"),
                    params=request.get("params"),
                )

            elapsed_ms = (datetime.now() - start_time).total_seconds() * 1000

            # 3. 执行断言
            assertions = self._run_assertions(case["expected"], response)

            # 4. 提取变量 (如 token)
            self._extract_variables(case.get("extract", {}), response)

            return {
                "case_id": case["case_id"],
                "case_name": case["case_name"],
                "case_type": case["case_type"],
                "passed": all(a["passed"] for a in assertions),
                "actual_status_code": response.status_code,
                "actual_response": response.json() if "application/json" in response.headers.get("content-type", "") else response.text,
                "response_time_ms": round(elapsed_ms, 2),
                "assertions": assertions,
                "error_detail": None if all(a["passed"] for a in assertions) else self._build_error_detail(assertions, response),
            }

        except httpx.TimeoutException:
            return {
                "case_id": case["case_id"],
                "case_name": case["case_name"],
                "passed": False,
                "error_type": "timeout",
                "error_detail": f"Request timed out after {self.timeout}s",
                "response_time_ms": self.timeout * 1000,
            }
        except Exception as e:
            return {
                "case_id": case["case_id"],
                "case_name": case["case_name"],
                "passed": False,
                "error_type": "connection_error",
                "error_detail": str(e),
                "response_time_ms": 0,
            }

    def _run_assertions(self, expected: dict, response: httpx.Response) -> list:
        """执行断言校验"""
        results = []

        # 状态码校验
        if "status_code" in expected:
            results.append({
                "type": "status_code",
                "passed": response.status_code == expected["status_code"],
                "expected": expected["status_code"],
                "actual": response.status_code,
            })

        # JSON Path 断言
        for assertion in expected.get("assertions", []):
            if assertion["type"] == "json_path":
                actual_value = self._extract_json_path(response.json(), assertion["path"])
                if assertion.get("operator") == "not_null":
                    passed = actual_value is not None
                elif assertion.get("operator") == "contains":
                    passed = assertion["expected"] in str(actual_value)
                else:
                    passed = actual_value == assertion.get("expected")

                results.append({
                    "type": "json_path",
                    "path": assertion["path"],
                    "passed": passed,
                    "expected": assertion.get("expected", assertion.get("operator")),
                    "actual": actual_value,
                })

        return results

    def _extract_variables(self, extract_config: dict, response: httpx.Response):
        """从响应中提取变量供后续用例使用"""
        if not extract_config:
            return

        try:
            body = response.json()
            for var_name, json_path in extract_config.items():
                value = self._extract_json_path(body, json_path)
                if value is not None:
                    self.variable_store[var_name] = value
        except:
            pass
```

### 5.2 性能自动化测试

#### 执行流程

```
性能测试流程
    │
    ├─ 1. 接口优先级评估
    │   AI 根据接口业务重要性、调用量预估、变更频率分配权重
    │   {
    │       "/api/v1/login": {"weight": 30, "reason": "高频核心接口"},
    │       "/api/v1/users/list": {"weight": 25, "reason": "管理后台高频"},
    │       "/api/v1/orders/create": {"weight": 20, "reason": "交易核心"},
    │       "/api/v1/config": {"weight": 5, "reason": "低频静态接口"},
    │   }
    │
    ├─ 2. 压测策略选择 (AI 根据接口特征自动选择)
    │   ├── 并发压测: 固定并发数，持续 N 秒，测量 TPS/RT
    │   ├── 阶梯压测: 逐步增加并发 (10→50→100→200→500)，找到拐点
    │   └── 稳定性压测: 中等负载持续 30 分钟，检测内存泄漏
    │
    ├─ 3. 压测执行 (基于 Locust)
    │   ┌──────────────────────────────────────────┐
    │   │ Locust Master + Workers 分布式压测        │
    │   │                                          │
    │   │  Master (调度)                            │
    │   │    ├── Worker 1 (模拟 100 用户)           │
    │   │    ├── Worker 2 (模拟 100 用户)           │
    │   │    └── Worker 3 (模拟 100 用户)           │
    │   │                                          │
    │   │  按权重分配请求:                          │
    │   │    login: 30% / list: 25% / create: 20%  │
    │   └──────────────────────────────────────────┘
    │
    ├─ 4. 指标采集
    │   - TPS (每秒事务数)
    │   - QPS (每秒请求数)
    │   - 平均/P50/P90/P95/P99 响应时间
    │   - 错误率
    │   - CPU/内存/网络 IO (通过容器监控)
    │
    ├─ 5. 瓶颈识别
    │   AI 分析:
    │   - 响应时间超过阈值的接口
    │   - 错误率突增的并发点
    │   - TPS 不再增长的拐点
    │   - 资源饱和点 (CPU > 80% / 内存 > 85%)
    │
    └─ 6. 结果输出
        {
            "api_path": "/api/v1/login",
            "test_type": "stepped",
            "metrics": {
                "max_tps": 1250.5,
                "avg_rt_ms": 45,
                "p95_rt_ms": 120,
                "p99_rt_ms": 250,
                "error_rate": 0.02,
                "breakpoint_concurrency": 300
            },
            "bottleneck": {
                "type": "response_time_degradation",
                "description": "并发超过 300 后 P95 响应时间从 120ms 飙升至 800ms",
                "likely_cause": "数据库连接池耗尽",
                "suggestion": "增加 HikariCP maximum-pool-size 至 50"
            }
        }
```

#### Locust 集成

```python
# modules/execution/performance_tester.py

from locust import HttpUser, task, between, events
import json

class APILoadTestUser(HttpUser):
    """Locust 性能测试用户 - 动态生成"""

    wait_time = between(0.5, 2)

    def on_start(self):
        """用户启动时登录获取 token"""
        response = self.client.post("/api/v1/login", json={
            "username": "perf_test_user",
            "password": "Test@1234"
        })
        if response.status_code == 200:
            self.token = response.json().get("data", {}).get("token", "")
            self.headers = {"Authorization": f"Bearer {self.token}"}
        else:
            self.token = None
            self.headers = {}

    @task(30)
    def test_login(self):
        self.client.post("/api/v1/login", json={
            "username": "perf_test_user",
            "password": "Test@1234"
        })

    @task(25)
    def test_user_list(self):
        self.client.get("/api/v1/users?page=1&size=20", headers=self.headers)

    @task(20)
    def test_create_order(self):
        self.client.post("/api/v1/orders", json={
            "productId": 1,
            "quantity": 1
        }, headers=self.headers)


class PerformanceTestRunner:
    """性能测试执行器"""

    def run_stepped_test(self, base_url: str, api_weights: dict) -> dict:
        """
        阶梯压测: 逐步增加并发用户

        阶梯: 10 → 50 → 100 → 200 → 500 → 1000
        每阶梯持续 60 秒
        """
        steps = [10, 50, 100, 200, 500, 1000]
        step_duration = 60  # seconds

        results = []
        for users in steps:
            step_result = self._run_step(base_url, users, step_duration, api_weights)
            results.append(step_result)

            # 如果错误率 > 5%，停止加压
            if step_result["error_rate"] > 0.05:
                break

        return self._analyze_results(results)

    def _run_step(self, base_url: str, users: int, duration: int, weights: dict) -> dict:
        """运行单个阶梯"""
        # 使用 Locust Headless 模式
        # ... Locust 进程启动和结果收集 ...
        pass
```

### 5.3 集成自动化测试

#### 执行流程

```
集成测试流程
    │
    ├─ 1. 依赖图分析
    │   AI 分析代码中的模块调用关系:
    │   {
    │       "modules": {
    │           "UserService": {
    │               "depends_on": ["Database", "SmsService"],
    │               "provides": ["createUser", "getUser", "updateUser"]
    │           },
    │           "OrderService": {
    │               "depends_on": ["UserService", "ProductService", "PaymentService"],
    │               "provides": ["createOrder", "cancelOrder"]
    │           }
    │       },
    │       "call_chains": [
    │           ["POST /api/orders", "OrderService.createOrder", "UserService.getUser", "PaymentService.charge"],
    │           ["POST /api/users", "UserService.createUser", "SmsService.sendCode"]
    │       ]
    │   }
    │
    ├─ 2. 全链路用例生成
    │   AI 基于调用链生成端到端测试场景:
    │   {
    │       "scenario": "用户注册→登录→下单→支付完整流程",
    │       "steps": [
    │           {"step": 1, "action": "POST /api/users", "expect": "用户创建成功"},
    │           {"step": 2, "action": "POST /api/login", "expect": "返回有效 token"},
    │           {"step": 3, "action": "GET /api/products/1", "expect": "返回商品信息"},
    │           {"step": 4, "action": "POST /api/orders", "expect": "订单创建成功"},
    │           {"step": 5, "action": "POST /api/payments", "expect": "支付成功"},
    │           {"step": 6, "action": "GET /api/orders/{orderId}", "expect": "订单状态为已支付"}
    │       ]
    │   }
    │
    ├─ 3. 场景串联执行
    │   ┌──────────────────────────────────────────┐
    │   │ Step 1: POST /api/users                  │
    │   │   → 提取 userId, 存入上下文              │
    │   │                                          │
    │   │ Step 2: POST /api/login                  │
    │   │   → 提取 token, 存入上下文               │
    │   │                                          │
    │   │ Step 3: GET /api/products/1              │
    │   │   → 验证商品存在, 提取 price             │
    │   │                                          │
    │   │ Step 4: POST /api/orders                 │
    │   │   → 使用 userId + productId 创建订单     │
    │   │   → 提取 orderId                         │
    │   │                                          │
    │   │ Step 5: POST /api/payments               │
    │   │   → 使用 orderId + price 发起支付        │
    │   │                                          │
    │   │ Step 6: GET /api/orders/{orderId}        │
    │   │   → 验证订单状态为已支付                 │
    │   └──────────────────────────────────────────┘
    │
    ├─ 4. 数据一致性校验
    │   - 跨接口数据传递是否正确
    │   - 数据库最终状态是否符合预期
    │   - 模块间数据格式是否兼容
    │
    ├─ 5. 流程闭环性验证
    │   - 业务流程是否完整（能否走到终态）
    │   - 异常分支是否正确处理
    │   - 回滚机制是否有效
    │
    └─ 6. 结果输出
        {
            "scenario": "用户注册→登录→下单→支付完整流程",
            "passed": false,
            "completed_steps": 4,
            "total_steps": 6,
            "failure_point": "Step 5: POST /api/payments",
            "failure_detail": "支付接口返回 500: 余额不足异常未捕获",
            "data_consistency": {
                "user_created": true,
                "order_created": true,
                "payment_completed": false,
                "final_order_status": "pending_payment"
            },
            "risk_points": [
                "支付失败后订单状态未回滚",
                "缺少支付超时处理机制"
            ]
        }
```

#### 集成测试执行代码

```python
# modules/execution/integration_tester.py

class IntegrationTestRunner:
    """集成测试执行器"""

    def __init__(self, base_url: str):
        self.base_url = base_url
        self.context = {}  # 上下文变量存储

    async def run_scenario(self, scenario: dict) -> dict:
        """执行一个集成测试场景"""
        steps = scenario["steps"]
        results = []

        for i, step in enumerate(steps):
            # 1. 准备请求 (替换上下文变量)
            request = self._interpolate(step["request"], self.context)

            # 2. 执行请求
            response = await self._execute_request(request)

            # 3. 校验响应
            step_passed = self._validate_step(response, step["expect"])

            # 4. 提取上下文变量
            if step.get("extract"):
                self._extract_to_context(response, step["extract"])

            results.append({
                "step": i + 1,
                "action": step["action"],
                "passed": step_passed,
                "status_code": response.status_code,
                "response": response.json() if response.headers.get("content-type", "").startswith("application/json") else response.text,
            })

            # 5. 如果步骤失败，根据策略决定是否继续
            if not step_passed:
                if step.get("stop_on_failure", True):
                    break

        # 6. 数据一致性检查
        consistency = await self._check_data_consistency(scenario, self.context)

        return {
            "scenario": scenario["scenario"],
            "passed": all(r["passed"] for r in results) and consistency["passed"],
            "completed_steps": len(results),
            "total_steps": len(steps),
            "failure_point": self._find_failure(results),
            "step_results": results,
            "data_consistency": consistency,
            "risk_points": self._identify_risks(results, consistency),
        }

    def _interpolate(self, request: dict, context: dict) -> dict:
        """替换请求中的上下文变量"""
        import re

        def replace_vars(obj):
            if isinstance(obj, str):
                return re.sub(
                    r'\{\{(\w+)\}\}',
                    lambda m: str(context.get(m.group(1), m.group(0))),
                    obj
                )
            elif isinstance(obj, dict):
                return {k: replace_vars(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [replace_vars(item) for item in obj]
            return obj

        return replace_vars(request)
```

---

## 六、测试报告完整字段与可视化设计方案

### 6.1 报告双模式架构

报告同时支持两种使用方式：

| 模式 | 格式 | 特点 | 适用场景 |
|------|------|------|---------|
| **在线查看** | 交互式 HTML | ECharts 可交互图表（缩放/筛选/tooltip）、用例详情展开折叠、实时数据刷新 | 日常浏览、团队分享链接、快速定位问题 |
| **PDF 导出** | 静态 PDF | matplotlib 静态图表、固定排版、适合打印 | 正式存档、邮件发送、合规审计、离线查看 |

```
测试完成后
    │
    ├─ 在线报告（自动生成）
    │   ├── 存储到 MinIO + 生成访问 URL
    │   ├── 平台内嵌浏览器直接打开
    │   ├── 交互式 ECharts 图表
    │   │   ├── 饼图：点击查看各类型详情
    │   │   ├── 柱状图：hover 显示精确数值
    │   │   ├── 折线图：可缩放时间范围
    │   │   └── 流程图：点击步骤查看详情
    │   ├── 失败用例表：展开查看请求/响应/断言详情
    │   └── 支持分享链接（带权限校验）
    │
    └─ PDF 导出（按需触发）
        ├── 点击「导出 PDF」按钮
        ├── 后台从相同数据渲染 PDF 专用模板
        ├── matplotlib 生成静态图表嵌入
        ├── WeasyPrint 转 PDF
        └── 浏览器下载
```

### 6.2 报告页面结构

```
┌─────────────────────────────────────────────────────────────────┐
│                    AI 自动化测试报告                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  📋 基础信息                                                    │
│  ┌─────────────┬─────────────┬─────────────┬─────────────┐     │
│  │ 数据源       │ 版本         │ 测试时间     │ 技术栈       │     │
│  │ GitHub/SVN/  │ branch=main │ 2026-01-15  │ Java/Spring │     │
│  │ 上传文件     │ abc1234     │ 10:30-10:42 │ Boot 3.2    │     │
│  ├─────────────┼─────────────┼─────────────┼─────────────┤     │
│  │ 环境         │ 执行时长     │ 质量评分     │ [导出 PDF]  │     │
│  │ Docker      │ 12m 35s     │ 78/100      │ [分享链接]  │     │
│  └─────────────┴─────────────┴─────────────┴─────────────┘     │
│                                                                 │
│  📊 整体结论                                                    │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ 质量评分: 78/100  │  上线风险: 中等  │  结论: 建议修复后上线 │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  🔍 代码解析结果                                                │
│  ┌──────────────┬──────────────┬──────────────┬────────────┐   │
│  │ 项目结构      │ 接口数量      │ 模块数量      │ 变更文件    │   │
│  │ 3层架构       │ 45 个 API    │ 8 个模块     │ 12 个文件   │   │
│  └──────────────┴──────────────┴──────────────┴────────────┘   │
│  [模块依赖关系图 - 桑基图]                                      │
│                                                                 │
│  🔌 接口测试详情                                                │
│  ┌──────────┬──────────┬──────────┬──────────┬──────────┐     │
│  │ 用例总数  │ 通过      │ 失败      │ 跳过      │ 通过率    │     │
│  │ 156      │ 142      │ 10       │ 4        │ 91.0%    │     │
│  └──────────┴──────────┴──────────┴──────────┴──────────┘     │
│  [通过/失败分布 - 饼图]                                         │
│  [各模块通过率 - 柱状图]                                        │
│  [失败用例明细表]                                               │
│                                                                 │
│  ⚡ 性能测试详情                                                │
│  ┌──────────────┬──────────────┬──────────────┬────────────┐   │
│  │ 测试接口数    │ 平均 TPS     │ 平均 RT      │ 瓶颈接口    │   │
│  │ 15           │ 850.5        │ 45ms         │ 3 个        │   │
│  └──────────────┴──────────────┴──────────────┴────────────┘   │
│  [TPS 趋势图 - 折线图]                                          │
│  [各接口响应时间对比 - 柱状图]                                  │
│  [瓶颈分析表]                                                   │
│                                                                 │
│  🔗 集成测试详情                                                │
│  ┌──────────────┬──────────────┬──────────────┬────────────┐   │
│  │ 测试场景数    │ 通过          │ 失败          │ 通过率      │   │
│  │ 12           │ 10           │ 2            │ 83.3%      │   │
│  └──────────────┴──────────────┴──────────────┴────────────┘   │
│  [全链路结果流程图]                                             │
│  [风险点列表]                                                   │
│                                                                 │
│  🐛 缺陷汇总                                                    │
│  ┌──────┬──────┬──────┬──────┬──────────────────────────┐     │
│  │ P0   │ P1   │ P2   │ P3   │ 总计                      │     │
│  │ 0    │ 3    │ 7    │ 5    │ 15                        │     │
│  └──────┴──────┴──────┴──────┴──────────────────────────┘     │
│  [缺陷分级分布 - 环形图]                                        │
│  [缺陷明细表: 级别|接口|描述|复现路径|成因|修复建议]            │
│                                                                 │
│  📈 优化建议                                                    │
│  1. 修复 /api/orders/create 的空指针异常 (P1)                   │
│  2. 增加 /api/users/list 分页缓存 (P2)                         │
│  3. 补充支付失败后订单状态回滚逻辑 (P1)                         │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 6.3 报告完整字段定义

```json
{
  "report_version": "1.0",
  "generated_at": "2026-01-15T10:45:00Z",

  "basic_info": {
    "source_type": "github",
    "repo_url": "https://github.com/owner/repo",
    "repo_name": "owner/repo",
    "branch": "main",
    "commit_sha": "abc1234567890abcdef",
    "commit_message": "feat: add user registration API",
    "svn_url": null,
    "svn_revision": null,
    "upload_filename": null,
    "version_id": "abc12345",
    "test_start_time": "2026-01-15T10:30:00Z",
    "test_end_time": "2026-01-15T10:42:35Z",
    "duration_seconds": 755,
    "tech_stack": {
      "language": "java",
      "framework": "spring-boot",
      "version": "3.2.1",
      "build_tool": "maven"
    },
    "environment": {
      "os": "linux",
      "runtime": "openjdk-17",
      "container_id": "a1b2c3d4",
      "base_url": "http://localhost:32785"
    }
  },

  "overall_conclusion": {
    "quality_score": 78,
    "quality_grade": "B",
    "pass": false,
    "risk_level": "medium",
    "risk_description": "存在 3 个 P1 级缺陷，建议修复后上线",
    "recommendation": "conditional_pass",
    "summary": "接口测试通过率 91%，性能指标达标，但集成测试中发现支付流程异常，建议修复 P1 缺陷后重新测试。"
  },

  "code_analysis": {
    "project_structure": {
      "type": "layered",
      "layers": ["controller", "service", "repository", "model"],
      "module_count": 8,
      "total_files": 156,
      "total_lines": 12450
    },
    "api_summary": {
      "total_apis": 45,
      "by_method": {"GET": 20, "POST": 15, "PUT": 6, "DELETE": 4},
      "by_module": {
        "UserController": 8,
        "OrderController": 12,
        "ProductController": 10,
        "AuthController": 5,
        "PaymentController": 6,
        "ConfigController": 4
      }
    },
    "dependency_graph": {
      "nodes": [
        {"id": "UserController", "type": "controller"},
        {"id": "UserService", "type": "service"},
        {"id": "UserRepository", "type": "repository"}
      ],
      "edges": [
        {"from": "UserController", "to": "UserService"},
        {"from": "UserService", "to": "UserRepository"}
      ]
    },
    "changed_files": [
      "src/main/java/com/example/controller/UserController.java",
      "src/main/java/com/example/service/UserService.java",
      "src/main/resources/application.yml"
    ],
    "change_analysis": {
      "added_apis": ["/api/v1/users/register"],
      "modified_apis": ["/api/v1/users/{id}"],
      "removed_apis": [],
      "affected_modules": ["UserController", "UserService"]
    }
  },

  "api_test_detail": {
    "total_cases": 156,
    "passed": 142,
    "failed": 10,
    "skipped": 4,
    "pass_rate": 0.91,
    "by_type": {
      "positive": {"total": 45, "passed": 43, "failed": 2},
      "negative": {"total": 60, "passed": 55, "failed": 5},
      "boundary": {"total": 30, "passed": 27, "failed": 3},
      "exception": {"total": 21, "passed": 17, "failed": 0}
    },
    "by_priority": {
      "P0": {"total": 30, "passed": 28, "failed": 2},
      "P1": {"total": 70, "passed": 64, "failed": 6},
      "P2": {"total": 40, "passed": 36, "failed": 2},
      "P3": {"total": 16, "passed": 14, "failed": 0}
    },
    "failed_cases": [
      {
        "case_id": "TC_015",
        "case_name": "注册接口-邮箱已存在",
        "api_path": "/api/v1/users/register",
        "method": "POST",
        "case_type": "negative",
        "priority": "P1",
        "expected_status": 400,
        "actual_status": 500,
        "error_detail": "Expected status 400, got 500. Response: {\"error\":\"Internal Server Error\",\"message\":\"duplicate key exception\"}",
        "response_time_ms": 125
      }
    ],
    "avg_response_time_ms": 45.2
  },

  "performance_test_detail": {
    "tested_apis": 15,
    "test_type": "stepped",
    "max_concurrency": 500,
    "overall_metrics": {
      "max_tps": 1250.5,
      "avg_tps": 850.3,
      "avg_rt_ms": 45,
      "p95_rt_ms": 120,
      "p99_rt_ms": 250,
      "error_rate": 0.008
    },
    "per_api_metrics": [
      {
        "api_path": "/api/v1/login",
        "method": "POST",
        "weight": 30,
        "max_tps": 380.5,
        "avg_rt_ms": 35,
        "p95_rt_ms": 85,
        "p99_rt_ms": 180,
        "error_rate": 0.002,
        "breakpoint_concurrency": 300
      }
    ],
    "bottleneck_apis": [
      {
        "api_path": "/api/v1/orders/create",
        "issue": "P95 响应时间 800ms 超过 200ms 阈值",
        "breakpoint": 200,
        "likely_cause": "数据库事务锁竞争",
        "suggestion": "优化事务隔离级别，添加乐观锁"
      }
    ],
    "stability_assessment": {
      "duration_minutes": 30,
      "memory_leak": false,
      "tps_degradation": 2.5,
      "verdict": "stable"
    }
  },

  "integration_test_detail": {
    "total_scenarios": 12,
    "passed": 10,
    "failed": 2,
    "pass_rate": 0.833,
    "scenarios": [
      {
        "scenario_name": "用户注册→登录→下单→支付",
        "passed": false,
        "completed_steps": 4,
        "total_steps": 6,
        "failure_point": "Step 5: POST /api/payments",
        "failure_detail": "支付接口返回 500",
        "data_consistency": {
          "user_created": true,
          "order_created": true,
          "payment_completed": false,
          "final_order_status": "pending_payment"
        },
        "risk_points": [
          "支付失败后订单状态未回滚",
          "缺少支付超时处理机制"
        ]
      }
    ],
    "module_interaction_validation": {
      "total_checks": 24,
      "passed": 22,
      "failed": 2,
      "issues": [
        "OrderService → PaymentService: 支付失败异常未正确传播",
        "UserService → SmsService: 短信发送失败未影响主流程（正确）"
      ]
    }
  },

  "defect_summary": {
    "total_defects": 15,
    "by_severity": {
      "P0": 0,
      "P1": 3,
      "P2": 7,
      "P3": 5
    },
    "by_category": {
      "program_bug": 5,
      "performance_issue": 3,
      "integration_failure": 2,
      "business_exception": 3,
      "security_vulnerability": 2
    },
    "defects": [
      {
        "defect_id": "DEF_001",
        "severity": "P1",
        "category": "program_bug",
        "title": "注册接口邮箱重复时返回 500 而非 400",
        "api_path": "/api/v1/users/register",
        "description": "当邮箱已存在时，接口返回 HTTP 500 和未处理的异常信息，而非预期的 400 状态码和友好错误提示",
        "reproduction_steps": [
          "1. 使用已注册的邮箱发起 POST /api/v1/users/register",
          "2. 观察返回状态码为 500",
          "3. 响应体包含 duplicate key exception"
        ],
        "root_cause": "UserService.register 方法未捕获 DataIntegrityViolationException，异常直接传播到 Controller 层",
        "fix_suggestion": "在 UserService.register 方法中添加 try-catch 块捕获 DataIntegrityViolationException，抛出自定义 BusinessException(400, \"邮箱已存在\")",
        "affected_files": ["src/main/java/com/example/service/UserService.java"],
        "related_test_case": "TC_015"
      }
    ]
  },

  "optimization_suggestions": [
    {
      "priority": "P1",
      "suggestion": "修复注册接口的异常处理，确保邮箱重复时返回 400",
      "effort": "low",
      "impact": "high"
    },
    {
      "priority": "P2",
      "suggestion": "为 /api/users/list 添加 Redis 缓存，减少数据库查询",
      "effort": "medium",
      "impact": "medium"
    },
    {
      "priority": "P1",
      "suggestion": "补充支付失败后订单状态回滚逻辑",
      "effort": "medium",
      "impact": "high"
    }
  ]
}
```

### 6.4 可视化方案

| 图表位置 | 图表类型 | 数据来源 | 展示内容 |
|---------|---------|---------|---------|
| 整体概览 | 指标卡片组 | overall_conclusion | 质量评分、通过率、缺陷数、风险等级 |
| 代码解析 | 桑基图 | dependency_graph | 模块间依赖流向 |
| 接口测试 | 饼图 | api_test_detail.by_type | 各类型用例通过/失败分布 |
| 接口测试 | 柱状图 | api_test_detail.by_module | 各模块通过率对比 |
| 接口测试 | 表格 | failed_cases | 失败用例明细（可展开详情） |
| 性能测试 | 折线图 | per_api_metrics | TPS 随并发数变化趋势 |
| 性能测试 | 柱状图 | per_api_metrics | 各接口 P95 响应时间对比 |
| 性能测试 | 表格 | bottleneck_apis | 瓶颈接口分析 |
| 集成测试 | 流程图 | scenarios | 全链路步骤通过/失败可视化 |
| 缺陷汇总 | 环形图 | by_severity | P0/P1/P2/P3 分布 |
| 缺陷汇总 | 表格 | defects | 缺陷明细（含复现路径和修复建议） |
| 历史对比 | 折线图 | 多次测试报告 | 质量评分趋势、缺陷数量趋势 |

---

## 七、平台部署、运行、使用全套落地步骤

### 7.1 环境要求

```
最低配置:
  - CPU: 4 核
  - 内存: 8 GB
  - 磁盘: 50 GB
  - OS: Linux (Ubuntu 22.04+ / CentOS 8+) 或 Docker Desktop

推荐配置:
  - CPU: 8 核+
  - 内存: 16 GB+
  - 磁盘: 200 GB+ SSD
  - OS: Ubuntu 22.04 LTS

必需软件:
  - Docker 20.10+
  - Docker Compose 2.0+
  - Git 2.30+
  - SVN 1.14+ (若需支持 SVN 仓库)

AI 模型配置（至少配置一个，支持运行时在平台页面修改）:
  - OpenAI API Key (GPT-4o 权限) — 或任意 OpenAI 兼容 API
  - 企业私有模型地址 (vLLM/Ollama 等) — 代码不离开内网
  - Anthropic API Key (Claude 3.5 Sonnet，可选备用)
```

### 7.2 部署步骤

```bash
# Step 1: 克隆平台仓库
git clone https://github.com/your-org/ai-test-platform.git
cd ai-test-platform

# Step 2: 配置环境变量
cp .env.example .env

# 编辑 .env 文件
cat > .env << 'EOF'
# === AI API (默认配置，可在平台「模型配置」页面修改) ===
# 支持任意 OpenAI 兼容 API，以下为默认值
OPENAI_API_KEY=sk-xxxxxxxxxxxxxxxxxxxx
OPENAI_API_BASE=https://api.openai.com/v1
OPENAI_MODEL_NAME=gpt-4o

# 备用模型（可选）
ANTHROPIC_API_KEY=sk-ant-xxxxxxxxxxxxxxxx
ANTHROPIC_API_BASE=https://api.anthropic.com/v1
ANTHROPIC_MODEL_NAME=claude-3-5-sonnet-20241022

# 企业私有模型示例（取消注释启用）
# CUSTOM_MODEL_API_BASE=http://10.0.1.100:8000/v1
# CUSTOM_MODEL_API_KEY=EMPTY
# CUSTOM_MODEL_NAME=Qwen/Qwen2.5-72B-Instruct

# === GitHub OAuth ===
GITHUB_CLIENT_ID=your_client_id
GITHUB_CLIENT_SECRET=your_client_secret
GITHUB_WEBHOOK_SECRET=your_webhook_secret

# === SVN ===
SVN_DEFAULT_USERNAME=svn_user
SVN_DEFAULT_PASSWORD=svn_password
SVN_WEBHOOK_SECRET=your_svn_webhook_secret

# === Database ===
POSTGRES_USER=aitest
POSTGRES_PASSWORD=secure_password_here
POSTGRES_DB=ai_test_platform

# === Redis ===
REDIS_PASSWORD=secure_redis_password

# === MinIO ===
MINIO_ROOT_USER=admin
MINIO_ROOT_PASSWORD=secure_minio_password

# === RabbitMQ ===
RABBITMQ_USER=admin
RABBITMQ_PASSWORD=secure_rabbit_password

# === Platform ===
PLATFORM_DOMAIN=http://localhost:8080
SECRET_KEY=your_flask_secret_key
EOF

# Step 3: 启动全部服务
docker-compose up -d

# 服务清单:
# - frontend      (Vue 3 前端, 端口 8080)
# - backend       (FastAPI 后端, 端口 8000)
# - celery-worker (任务执行器, 3 个实例)
# - celery-beat   (定时任务调度)
# - postgres      (数据库, 端口 5432)
# - redis         (缓存/队列, 端口 6379)
# - rabbitmq      (消息队列, 端口 5672)
# - minio         (对象存储, 端口 9000)

# Step 4: 初始化数据库
docker-compose exec backend alembic upgrade head
docker-compose exec backend python scripts/init_data.py

# Step 5: 验证部署
curl http://localhost:8000/health
# 期望返回: {"status": "healthy", "version": "1.0.0"}

# Step 6: 访问平台
# 浏览器打开: http://localhost:8080
```

### 7.3 Docker Compose 配置

```yaml
# docker-compose.yml
version: "3.8"

services:
  frontend:
    build: ./frontend
    ports:
      - "8080:80"
    depends_on:
      - backend
    environment:
      - VITE_API_BASE=http://localhost:8000

  backend:
    build: ./backend
    ports:
      - "8000:8000"
    depends_on:
      - postgres
      - redis
      - rabbitmq
    env_file: .env
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock  # Docker SDK 访问
      - ./data/repos:/data/repos                    # 代码存储
      - ./data/reports:/data/reports                # 报告存储

  celery-worker:
    build: ./backend
    command: celery -A app.celery worker -l info -c 4
    depends_on:
      - rabbitmq
      - redis
    env_file: .env
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - ./data/repos:/data/repos
      - ./data/reports:/data/reports
    deploy:
      replicas: 3

  celery-beat:
    build: ./backend
    command: celery -A app.celery beat -l info
    depends_on:
      - rabbitmq
    env_file: .env

  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: ${POSTGRES_DB}
    volumes:
      - pgdata:/var/lib/postgresql/data
    ports:
      - "5432:5432"

  redis:
    image: redis:7-alpine
    command: redis-server --requirepass ${REDIS_PASSWORD}
    ports:
      - "6379:6379"

  rabbitmq:
    image: rabbitmq:3.12-management-alpine
    environment:
      RABBITMQ_DEFAULT_USER: ${RABBITMQ_USER}
      RABBITMQ_DEFAULT_PASS: ${RABBITMQ_PASSWORD}
    ports:
      - "5672:5672"
      - "15672:15672"  # 管理界面

  minio:
    image: minio/minio:latest
    command: server /data --console-address ":9001"
    environment:
      MINIO_ROOT_USER: ${MINIO_ROOT_USER}
      MINIO_ROOT_PASSWORD: ${MINIO_ROOT_PASSWORD}
    volumes:
      - miniodata:/data
    ports:
      - "9000:9000"
      - "9001:9001"  # 控制台

volumes:
  pgdata:
  miniodata:
```

### 7.4 使用流程

```
Step 1: 选择数据源（三选一）
  ├── 方式A: GitHub 仓库
  │   ├── 点击「连接 GitHub」按钮
  │   ├── 跳转 GitHub 授权页面
  │   ├── 授权后自动返回平台
  │   ├── 选择目标仓库 → 选择分支/Commit
  │   └── 可选：配置 Webhook 自动触发
  │
  ├── 方式B: SVN 仓库
  │   ├── 点击「添加 SVN 仓库」
  │   ├── 填写 SVN URL + 账号密码
  │   ├── 平台验证连接
  │   ├── 选择修订版本（默认最新）
  │   └── 可选：配置 post-commit Hook 自动触发
  │
  └── 方式C: 人工上传
      ├── 点击「上传代码」或拖拽文件
      ├── 选择 ZIP/TAR.GZ 压缩包（≤500MB）
      ├── 等待上传完成
      └── 自动进入测试流程

Step 2: 配置测试参数（可选）
  ├── 选择分支 (默认 main)
  ├── 选择 Commit (默认最新)
  ├── 选择测试类型 (默认全选)
  ├── 设置性能压测参数 (可选)
  │   ├── 最大并发数 (默认 500)
  │   ├── 压测持续时间 (默认 60s/阶梯)
  │   └── 压测策略 (默认阶梯压测)
  └── 设置 Webhook 自动触发 (可选)

Step 3: 启动测试
  ├── 点击「开始测试」
  ├── 平台创建测试任务
  └── 跳转到实时进度页面

Step 4: 查看实时进度
  ├── 代码拉取进度 (进度条)
  ├── AI 解析进度 (步骤指示器)
  ├── 用例生成进度 (计数器)
  ├── 测试执行进度 (实时日志 + 通过/失败计数)
  └── 报告生成进度 (进度条)

Step 5: 查看测试报告
  ├── 测试完成后自动跳转报告页
  ├── 在线交互式查看 HTML 报告
  │   ├── 图表可交互（缩放/筛选/hover 详情）
  │   ├── 失败用例可展开查看请求/响应/断言
  │   └── 支持分享链接给团队成员
  ├── 导出 PDF 报告（点击「导出 PDF」按钮）
  ├── 查看历史测试记录
  └── 对比两次测试结果

Step 6: 后续操作
  ├── 查看缺陷详情和修复建议
  ├── 导出缺陷清单到 Issue Tracker
  ├── 设置定时测试 (每日/每周)
  └── 配置 CI/CD 集成
```

---

## 八、异常容错与优化扩展方案

### 8.1 异常容错机制

| 异常场景 | 检测方式 | 处理策略 | 兜底方案 |
|---------|---------|---------|---------|
| **代码拉取失败** | Git/SVN 命令异常/网络超时 | 指数退避重试 3 次 (5s→10s→20s) | 使用上次成功快照 |
| **SVN 认证失败** | svn 返回认证错误 | 提示用户检查凭据，不重试 | 标记任务失败，通知用户 |
| **上传文件损坏** | 解压失败/MD5 不匹配 | 拒绝并提示用户重新上传 | 标记任务失败 |
| **AI API 限流** | HTTP 429 响应 | 等待 Retry-After 后重试，最多 5 次 | 切换备用模型 (GPT→Claude) |
| **AI 响应超时** | 请求超过 60s 无响应 | 重试 2 次 | 跳过该接口的 AI 分析，使用规则匹配 |
| **AI 返回格式异常** | JSON 解析失败 | 重试 2 次 (降低 temperature) | 使用预定义模板生成基础用例 |
| **接口测试超时** | 响应超过 30s | 标记为超时，继续下一个用例 | 在报告中标注超时 |
| **被测服务启动失败** | 健康检查 3 次失败 | 重启容器 3 次 | 标记环境异常，跳过该模块测试 |
| **被测服务崩溃** | 容器退出 | 自动重启 + 记录崩溃日志 | 降级为接口测试（跳过性能/集成） |
| **数据库连接失败** | 连接池超时 | 重试 3 次 (5s 间隔) | 降级为文件存储结果 |
| **磁盘空间不足** | 磁盘使用率 > 90% | 清理旧快照和日志 | 发送告警，暂停新任务 |
| **任务中断** | Celery worker 崩溃 | 从检查点恢复 | 从头重新执行 |
| **Docker 资源不足** | OOM 或 CPU 限制 | 降低并发度重试 | 串行执行 |

### 8.2 检查点与恢复机制

```python
# modules/monitor/checkpoint.py

class CheckpointManager:
    """任务检查点管理器"""

    def save_checkpoint(self, test_run_id: str, module: str, state: dict):
        """保存检查点"""
        checkpoint = {
            "test_run_id": test_run_id,
            "module": module,
            "state": state,
            "timestamp": datetime.utcnow().isoformat(),
        }
        # 保存到 Redis（快速恢复）+ PostgreSQL（持久化）
        redis_client.set(f"checkpoint:{test_run_id}:{module}", json.dumps(checkpoint))
        db.save_checkpoint(checkpoint)

    def load_checkpoint(self, test_run_id: str) -> dict | None:
        """加载最新检查点"""
        # 优先从 Redis 加载
        for module in ["puller", "analyzer", "generator", "executor", "defect", "report"]:
            data = redis_client.get(f"checkpoint:{test_run_id}:{module}")
            if data:
                return json.loads(data)
        # 降级到 PostgreSQL
        return db.get_latest_checkpoint(test_run_id)

    def resume_from_checkpoint(self, test_run_id: str) -> str:
        """从检查点恢复任务"""
        checkpoint = self.load_checkpoint(test_run_id)
        if not checkpoint:
            return "no_checkpoint_found"

        module = checkpoint["module"]
        state = checkpoint["state"]

        # 根据模块恢复到对应步骤
        if module == "puller":
            # 代码已拉取，跳到分析阶段
            return resume_analysis(test_run_id, state)
        elif module == "analyzer":
            # 分析已完成，跳到用例生成
            return resume_generation(test_run_id, state)
        elif module == "generator":
            # 用例已生成，跳到执行
            return resume_execution(test_run_id, state)
        elif module == "executor":
            # 部分测试已执行，恢复未完成的部分
            return resume_remaining_tests(test_run_id, state)
```

### 8.3 优化扩展方案

#### 扩展方向一：支持更多技术栈

```python
# 新增技术栈只需实现两个适配器
# 1. 代码解析适配器
class RustActixExtractor:
    """Rust Actix-web 接口提取器"""
    ROUTE_PATTERN = re.compile(r'\.route\(\s*"([^"]+)"\s*,\s*(\w+)')
    # ...

# 2. 环境启动适配器
class RustActixAdapter(EnvironmentAdapter):
    def start_service(self, repo_path: str) -> str:
        # cargo build && ./target/debug/app
        # ...

# 注册到工厂
EnvironmentAdapterFactory.ADAPTERS["rust_actix"] = RustActixAdapter
```

#### 扩展方向二：自定义测试类型

```python
# 通过插件机制扩展新测试类型
class CustomTestPlugin:
    """自定义测试插件接口"""
    name = "security_scan"

    def generate_cases(self, analysis_result: dict) -> list:
        """生成测试用例"""
        pass

    def execute(self, cases: list, base_url: str) -> list:
        """执行测试"""
        pass

    def analyze_results(self, results: list) -> dict:
        """分析结果"""
        pass

# 注册插件
plugin_registry.register(CustomTestPlugin)
```

#### 扩展方向三：CI/CD 集成

```yaml
# .github/workflows/ai-test.yml
name: AI Automated Testing

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main]

jobs:
  ai-test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Trigger AI Test Platform
        run: |
          curl -X POST https://your-platform-domain/api/test-runs \
            -H "Authorization: Bearer ${{ secrets.PLATFORM_TOKEN }}" \
            -H "Content-Type: application/json" \
            -d "{
              \"repo_url\": \"${{ github.repository }}\",
              \"branch\": \"${{ github.ref_name }}\",
              \"commit_sha\": \"${{ github.sha }}\",
              \"trigger\": \"ci\"
            }"

      - name: Wait for test completion
        run: |
          # 轮询测试状态
          STATUS="running"
          while [ "$STATUS" = "running" ]; do
            sleep 30
            STATUS=$(curl -s https://your-platform-domain/api/test-runs/${RUN_ID}/status \
              -H "Authorization: Bearer ${{ secrets.PLATFORM_TOKEN }}" | jq -r '.status')
          done

          if [ "$STATUS" != "passed" ]; then
            echo "Tests failed!"
            exit 1
          fi
```

#### 扩展方向四：水平扩展

```
扩展策略:
┌─────────────────────────────────────────────────────┐
│                    负载均衡器                         │
│              (Nginx / HAProxy)                       │
├──────────┬──────────┬──────────┬────────────────────┤
│ Backend  │ Backend  │ Backend  │  ...               │
│ Node 1   │ Node 2   │ Node 3   │                    │
├──────────┴──────────┴──────────┴────────────────────┤
│                  共享存储层                           │
│  PostgreSQL (主从) + Redis (集群) + MinIO (分布式)   │
├──────────────────────────────────────────────────────┤
│              Celery Worker 集群                      │
│  ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐       │
│  │Worker 1│ │Worker 2│ │Worker 3│ │Worker N│       │
│  │(API)   │ │(Perf)  │ │(Integ) │ │(Mixed) │       │
│  └────────┘ └────────┘ └────────┘ └────────┘       │
└──────────────────────────────────────────────────────┘

扩展指标:
- 单节点支持 5 个并发测试任务
- 每增加 1 个 Worker 节点，支持 +5 并发任务
- 数据库读写分离: 1 主 + 2 从
- Redis 集群: 3 主 + 3 从
- MinIO 分布式: 最少 4 节点
```

#### 扩展方向五：AI 模型优化

```python
# 模型微调与缓存策略
class AIModelOptimizer:
    """AI 模型调用优化"""

    def __init__(self):
        self.cache = RedisCache()
        self.model_router = ModelRouter()

    def analyze_code(self, code: str, context: dict) -> dict:
        # 1. 检查缓存 (相同代码不需要重复分析)
        cache_key = hashlib.md5(code.encode()).hexdigest()
        cached = self.cache.get(f"analysis:{cache_key}")
        if cached:
            return cached

        # 2. 路由到合适的模型
        model = self.model_router.select_model(
            code_length=len(code),
            complexity=context.get("complexity", "medium"),
            cost_budget=context.get("cost_budget", "standard"),
        )

        # 3. 调用模型
        result = self._call_model(model, code, context)

        # 4. 缓存结果 (TTL 24h)
        self.cache.set(f"analysis:{cache_key}", result, ttl=86400)

        return result

    # 批量优化: 合并多个接口的分析请求
    async def batch_analyze(self, apis: list) -> list:
        """批量分析接口，减少 API 调用次数"""
        # 将多个接口代码合并到一个 prompt 中
        batches = self._create_batches(apis, max_tokens=4000)

        results = await asyncio.gather(*[
            self._analyze_batch(batch) for batch in batches
        ])

        return self._merge_results(results)
```

---

## 九、企业级增强方案

> 以下为基于架构师视角，针对企业级落地场景提出的增强建议。每项均可独立实施，不影响核心流程。

### 9.1 多租户与 RBAC 权限管理

**问题**：当前方案无用户体系，企业多团队使用时无法隔离项目和数据。

**方案**：

```
┌──────────────────────────────────────────────────────────┐
│                     RBAC 权限模型                          │
│                                                          │
│  组织(Org)                                                │
│    └── 项目(Project)                                      │
│          ├── 成员(Member) ── 角色(Role)                   │
│          │   ├── Admin    : 全部操作+配置                  │
│          │   ├── Tester   : 发起测试+查看报告              │
│          │   ├── Developer: 查看报告+缺陷                 │
│          │   └── Viewer   : 只读报告                      │
│          ├── 数据源配置(GitHub/SVN/Upload)                 │
│          ├── 测试记录                                      │
│          └── 报告                                         │
│                                                          │
│  数据隔离: 项目间数据完全隔离，跨项目需显式授权              │
│  资源配额: 每个项目可配置最大并发测试数、月度执行上限         │
└──────────────────────────────────────────────────────────┘
```

```python
# modules/auth/rbac.py

class Permission(Enum):
    PROJECT_MANAGE = "project:manage"      # 管理项目配置
    TEST_RUN = "test:run"                   # 发起测试
    TEST_CANCEL = "test:cancel"             # 取消测试
    REPORT_VIEW = "report:view"             # 查看报告
    REPORT_EXPORT = "report:export"         # 导出报告
    MODEL_CONFIG = "model:config"           # 配置 AI 模型
    SOURCE_CONFIG = "source:config"         # 配置数据源
    USER_MANAGE = "user:manage"             # 管理成员

ROLE_PERMISSIONS = {
    "admin": list(Permission),                                          # 全部权限
    "tester": [Permission.TEST_RUN, Permission.TEST_CANCEL,
               Permission.REPORT_VIEW, Permission.REPORT_EXPORT],
    "developer": [Permission.REPORT_VIEW, Permission.REPORT_EXPORT],
    "viewer": [Permission.REPORT_VIEW],
}

def check_permission(user_id: str, project_id: str, permission: Permission) -> bool:
    """检查用户在项目中的权限"""
    role = get_user_role(user_id, project_id)
    return permission in ROLE_PERMISSIONS.get(role, [])
```

### 9.2 审计日志

**问题**：企业合规要求记录「谁在什么时候对什么做了什么操作」。

**方案**：

```python
# modules/audit/logger.py

class AuditLogger:
    """审计日志 — 记录所有关键操作"""

    async def log(self, user_id: str, action: str, resource_type: str,
                  resource_id: str, detail: dict, ip: str):
        """
        记录审计日志

        示例:
        - user=u123, action="test.run", resource="project:p456",
          detail={"source": "github", "repo": "owner/repo", "branch": "main"}
        - user=u123, action="model.config.update", resource="model:azure-gpt4",
          detail={"changed": "api_base_url"}
        - user=u123, action="report.export", resource="test_run:tr789",
          detail={"format": "pdf"}
        """
        audit_entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "user_id": user_id,
            "action": action,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "detail": detail,
            "ip": ip,
        }
        # 写入 PostgreSQL 审计表 + Elasticsearch（用于全文检索）
        await db.audit_log.insert(audit_entry)
        await es.index(index="audit-logs", document=audit_entry)

# 通过中间件自动记录
@app.middleware("http")
async def audit_middleware(request: Request, call_next):
    if request.method in ("POST", "PUT", "DELETE"):
        user = get_current_user(request)
        await AuditLogger.log(
            user_id=user.id,
            action=f"{request.method.lower()}.{request.url.path}",
            resource_type="api",
            resource_id=request.url.path,
            detail={"body": await request.body()},
            ip=request.client.host,
        )
    return await call_next(request)
```

### 9.3 代码隐私与数据安全

**问题**：企业代码是核心资产，不能发送到外部 AI API。当前方案虽支持私有模型，但需明确数据安全策略。

**方案**：

| 安全层级 | 措施 | 说明 |
|---------|------|------|
| **传输安全** | 全链路 HTTPS/TLS | 代码传输、API 调用全程加密 |
| **存储安全** | 代码快照加密存储 | MinIO 对象加密 + 访问临时 URL 过期 |
| **模型安全** | 支持纯私有部署 | 配置私有 LLM（vLLM/Ollama），代码不离开内网 |
| **代码脱敏** | AI 调用前自动脱敏 | 正则替换密钥、Token、密码等敏感信息后再发给 AI |
| **数据清理** | 测试完成后自动清理 | 可配置保留天数，到期自动删除代码快照 |
| **网络隔离** | 支持 Air-gap 部署 | 平台可部署在无外网环境，仅依赖内网模型 |

```python
# modules/security/desensitizer.py

class CodeDesensitizer:
    """代码脱敏 — AI 调用前移除敏感信息"""

    SENSITIVE_PATTERNS = [
        # API Keys
        (re.compile(r'(sk-|sk-ant-)[a-zA-Z0-9]{20,}'), r'\1***REDACTED***'),
        # 数据库密码
        (re.compile(r'(password|passwd|pwd)\s*[=:]\s*["\']?([^"\'\s]+)', re.I),
         r'\1=***REDACTED***'),
        # JWT Token
        (re.compile(r'eyJ[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}'),
         '***JWT_REDACTED***'),
        # AWS Keys
        (re.compile(r'AKIA[0-9A-Z]{16}'), '***AWS_KEY_REDACTED***'),
        # 连接字符串中的密码
        (re.compile(r'(mongodb|postgres|mysql|redis)://[^:]+:([^@]+)@'),
         r'\1://***:***REDACTED***@'),
    ]

    def desensitize(self, code: str) -> str:
        """脱敏代码内容"""
        for pattern, replacement in self.SENSITIVE_PATTERNS:
            code = pattern.sub(replacement, code)
        return code

    def desensitize_config(self, config: dict) -> dict:
        """脱敏配置文件中的敏感字段"""
        sensitive_keys = {"password", "secret", "token", "api_key", "private_key"}
        result = {}
        for k, v in config.items():
            if any(sk in k.lower() for sk in sensitive_keys):
                result[k] = "***REDACTED***"
            elif isinstance(v, dict):
                result[k] = self.desensitize_config(v)
            else:
                result[k] = v
        return result
```

### 9.4 通知与告警集成

**问题**：测试完成后需要主动通知相关人员，而非被动查看。

**方案**：

```python
# modules/notification/notifier.py

class NotificationManager:
    """多渠道通知管理器"""

    def __init__(self):
        self.channels = []  # 运行时注册通知渠道

    def register_channel(self, channel: NotificationChannel):
        self.channels.append(channel)

    async def notify_test_completed(self, test_run: dict, report: dict):
        """测试完成后发送通知"""
        summary = report["summary"]
        message = self._build_message(test_run, summary)

        # 根据结果决定通知级别
        if summary["overall_conclusion"]["pass"]:
            level = "success"
        elif summary["defect_summary"]["by_severity"]["P0"] > 0:
            level = "critical"  # P0 缺陷 → 紧急通知
        else:
            level = "warning"

        for channel in self.channels:
            try:
                await channel.send(message, level=level)
            except Exception as e:
                logger.error(f"Notification failed on {channel.name}: {e}")

# 支持的通知渠道
class EmailChannel(NotificationChannel):
    """邮件通知"""

class WebhookChannel(NotificationChannel):
    """通用 Webhook（飞书/钉钉/企业微信/Slack）"""
    # 飞书: https://open.feishu.cn/open-apis/bot/v2/hook/xxx
    # 钉钉: https://oapi.dingtalk.com/robot/send?access_token=xxx
    # 企微: https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx

class DingTalkChannel(WebhookChannel):
    """钉钉机器人通知"""
    def format_message(self, content: dict, level: str) -> dict:
        title = "✅ 测试通过" if level == "success" else "❌ 测试失败"
        if level == "critical":
            title = "🚨 发现 P0 缺陷！"
        return {
            "msgtype": "markdown",
            "markdown": {
                "title": title,
                "text": self._to_markdown(content)
            }
        }
```

### 9.5 质量门禁（Quality Gate）

**问题**：企业需要定义「测试通过/不通过」的客观标准，作为上线门禁。

**方案**：

```python
# modules/quality_gate/gate.py

class QualityGate:
    """
    质量门禁 — 定义上线通过标准

    企业可自定义门禁规则，测试结果不满足规则时阻断上线。
    """

    DEFAULT_RULES = {
        "max_p0_defects": 0,        # P0 缺陷必须为 0
        "max_p1_defects": 2,        # P1 缺陷不超过 2 个
        "min_api_pass_rate": 0.90,  # 接口测试通过率不低于 90%
        "min_integration_pass_rate": 0.80,  # 集成测试通过率不低于 80%
        "max_response_time_p95_ms": 500,    # P95 响应时间不超过 500ms
        "max_error_rate": 0.05,             # 错误率不超过 5%
        "min_quality_score": 70,            # 质量评分不低于 70
    }

    def evaluate(self, report: dict, custom_rules: dict | None = None) -> dict:
        """评估是否通过质量门禁"""
        rules = {**self.DEFAULT_RULES, **(custom_rules or {})}
        results = []

        # 检查每条规则
        p0 = report["defect_summary"]["by_severity"]["P0"]
        results.append({
            "rule": "P0 缺陷数",
            "threshold": f"≤ {rules['max_p0_defects']}",
            "actual": p0,
            "passed": p0 <= rules["max_p0_defects"],
        })

        api_pass = report["api_test_detail"]["pass_rate"]
        results.append({
            "rule": "接口测试通过率",
            "threshold": f"≥ {rules['min_api_pass_rate']:.0%}",
            "actual": f"{api_pass:.1%}",
            "passed": api_pass >= rules["min_api_pass_rate"],
        })

        # ... 其他规则检查 ...

        all_passed = all(r["passed"] for r in results)

        return {
            "gate_passed": all_passed,
            "rules_checked": results,
            "blocking_issues": [r for r in results if not r["passed"]],
            "recommendation": "通过" if all_passed else "不通过 — 存在未满足的门禁规则",
        }
```

### 9.6 历史趋势看板

**问题**：单次测试报告只能看到当前状态，无法感知质量趋势。

**方案**：

```
质量趋势看板
┌──────────────────────────────────────────────────────┐
│  项目: owner/repo    时间范围: 近30天                  │
│                                                      │
│  📈 质量评分趋势                                      │
│  ┌──────────────────────────────────────────┐        │
│  │     85                                    │        │
│  │  80 ╱╲    ╱──╲    78                      │        │
│  │  75   ╲──╯    ╲──╲                        │        │
│  │  70                  ╲──70                 │        │
│  │  ──┴──┴──┴──┴──┴──┴──┴──                  │        │
│  │  08/01  08/05  08/10  08/15  08/20        │        │
│  └──────────────────────────────────────────┘        │
│                                                      │
│  📊 缺陷数量趋势                                      │
│  ┌──────────────────────────────────────────┐        │
│  │  P0: 0  0  0  0  1  0  0  0  0  0        │        │
│  │  P1: 3  2  4  2  5  3  2  3  2  3        │        │
│  │  P2: 7  5  8  6  9  7  5  7  6  7        │        │
│  └──────────────────────────────────────────┘        │
│                                                      │
│  📋 接口通过率趋势                                    │
│  ┌──────────────────────────────────────────┐        │
│  │  95%──╮                                 │        │
│  │  90%  ╰──╮  ╱──╮                        │        │
│  │  85%     ╰──╯   ╰──91%──                │        │
│  └──────────────────────────────────────────┘        │
│                                                      │
│  🔍 关键指标                                          │
│  ├── 平均质量评分: 78.5 (近30天)                      │
│  ├── 质量趋势: ↗ 改善中 (+8.5 vs 上月)               │
│  ├── 最常见缺陷类型: program_bug (占 42%)             │
│  └── 最不稳定接口: /api/v1/orders/create (3次失败)    │
└──────────────────────────────────────────────────────┘
```

### 9.7 测试环境管理增强

**问题**：当前方案依赖 Docker 自动构建被测服务，但企业往往有预置的测试环境（如 K8s 集群、共享测试服务器）。

**方案**：支持两种环境模式：

| 模式 | 说明 | 适用场景 |
|------|------|---------|
| **自动构建模式** | 平台自动构建 Docker 镜像并启动被测服务 | 新项目、CI/CD 集成 |
| **连接模式** | 用户配置已有的测试环境地址，平台直接连接测试 | 已有测试环境的企业、微服务联调环境 |

```python
# modules/execution/env_manager.py

class EnvironmentManager:
    """测试环境管理器"""

    async def prepare(self, config: EnvironmentConfig) -> dict:
        if config.mode == "auto_build":
            # 自动构建并启动被测服务（现有逻辑）
            adapter = EnvironmentAdapterFactory.get_adapter(config.tech_stack)
            service_url = adapter.start_service(config.repo_path)
            return {"url": service_url, "mode": "auto_build"}

        elif config.mode == "connect":
            # 连接已有测试环境
            service_url = config.predefined_url
            # 验证连通性
            if not await self._check_connectivity(service_url):
                raise ConnectionError(f"Cannot reach predefined env: {service_url}")
            return {"url": service_url, "mode": "connect"}

    async def _check_connectivity(self, url: str) -> bool:
        """验证测试环境连通性"""
        import httpx
        try:
            r = await httpx.AsyncClient().get(f"{url}/health", timeout=10)
            return r.status_code < 500
        except:
            return False
```

### 9.8 API Mock 与依赖隔离

**问题**：微服务架构下，被测服务依赖其他服务（数据库、消息队列、第三方 API），测试时这些依赖可能不可用。

**方案**：集成 Mock Server，自动生成依赖服务的 Mock：

```python
# modules/mock/mock_server.py

class DependencyMocker:
    """
    依赖 Mock 服务器

    AI 分析代码中的外部依赖（数据库调用、HTTP 调用、消息队列），
    自动生成 Mock 响应，使被测服务可以独立运行。
    """

    async def analyze_dependencies(self, code_path: str) -> list:
        """AI 分析代码中的外部依赖"""
        # 识别: HTTP 调用、数据库操作、消息队列、第三方 SDK 调用
        # 返回: [{"type": "http", "url": "http://payment-service/charge", "method": "POST"}, ...]
        ...

    async def generate_mocks(self, dependencies: list) -> dict:
        """为每个依赖生成 Mock 响应"""
        # AI 根据依赖的调用上下文生成合理的 Mock 响应
        ...

    async def start_mock_server(self, mocks: dict) -> str:
        """启动 Mock 服务器"""
        # 返回 mock server URL，被测服务配置指向此地址
        ...
```

### 9.9 企业级增强方案实施优先级

| 优先级 | 增强项 | 实施难度 | 企业价值 | 建议阶段 |
|--------|--------|---------|---------|---------|
| **P0** | 多租户与 RBAC | 中 | 高 | MVP 阶段 |
| **P0** | 代码隐私与脱敏 | 低 | 高 | MVP 阶段 |
| **P1** | 质量门禁 | 低 | 高 | V1.0 |
| **P1** | 通知与告警集成 | 低 | 高 | V1.0 |
| **P1** | 审计日志 | 中 | 中 | V1.0 |
| **P2** | 测试环境管理增强 | 中 | 中 | V1.1 |
| **P2** | 历史趋势看板 | 中 | 中 | V1.1 |
| **P3** | API Mock 与依赖隔离 | 高 | 中 | V2.0 |

---

## 十、九大 AI 能力实现状态与新增模块（V3）

> 本节为 V3 版本新增，用于汇总平台「九大 AI 能力」的实现状态，并补充能力 5–9（前置/后置脚本生成、SQL 脚本生成、定时任务、报告分析）对应的后端模块、API 与前端页面。能力 1–4 已在第三、九章的主体模块设计中实现，此处一并纳入状态矩阵。

### 10.1 九大 AI 能力实现状态矩阵

| 编号 | 能力 | 后端模块 | 前端页面 | 状态 | 备注 |
|------|------|----------|----------|------|------|
| 能力 1 | 文档解析 | `api/doc.py` + `modules/code_analyzer` | — | ✅ 已完成 | 接口文档解析 + 代码语义分析 |
| 能力 2 | 文档评审 | `api/doc.py`（reviews） | — | ✅ 已完成 | 评审意见生成 |
| 能力 3 | 用例生成 | `api/case_library.py` + `modules/case_generator` | — | ✅ 已完成 | 用例库资产 + AI 生成/采纳 |
| 能力 4 | 场景编排 | `api/scenario.py` | — | ✅ 已完成 | 场景编排 + dry-run + 采纳 |
| 能力 5 | 前置脚本生成 | `api/scripts.py` + `modules/script_gen` | `ScriptPanel.vue` | ✅ 已完成 | 统一入口 `/api/scripts/generate` |
| 能力 6 | 后置脚本生成 | `api/scripts.py` + `modules/script_gen` | `ScriptPanel.vue` | ✅ 已完成 | 同能力 5，`script_type` 区分 |
| 能力 7 | SQL 脚本生成 | `modules/sql_gen` + `api/databases.py` | `ScriptPanel.vue` + `DatabaseManage.vue` | ✅ 已完成 | 经 `/api/scripts/generate`（sql_script）暴露；依赖数据库连接管理 |
| 能力 8 | 定时任务 | `api/scheduled_tasks.py` + `modules/scheduler` | `ScheduledTasks.vue` | ⚠️ 基本完成 | CRUD / 自然语言解析 / Celery 调度就绪；**真实执行链为降级记录（TODO）** |
| 能力 9 | 报告分析 | `api/report_analysis.py` + `modules/report_analysis` | `ReportAnalysis.vue` | ✅ 已完成 | 失败分析 / 报告摘要 / 对比 三态 |

> 图例：✅ 已完成 = 后端 + 前端 + 契约已对齐，可联调；⚠️ 基本完成 = 主体可用，存在已知降级点（见 10.4 / 10.6）。

### 10.2 能力 5/6：前置 / 后置脚本生成

自然语言描述 → 可执行脚本生成，统一入口支持 `pre_script` / `post_script` / `sql_script` 三种类型。

- **API**：`backend/app/api/scripts.py`
  - `POST /api/scripts/generate` — 生成脚本（按 `script_type` 路由到 pre/post/sql）
  - `POST /api/scripts/preview` — 预览生成结果（不落库）
- **Schema**：`backend/app/schemas/script.py`（`ScriptGenerateRequest`：`script_type`、`nl_input`、`context`、`project_id`；`ScriptPreviewRequest`）
- **Module**：`backend/app/modules/script_gen/script_generator.py`（`ScriptGenerator.generate` / `preview`，写入 `ScriptGenerationRecord`，可经 `PUT /api/cases/{case_id}/scripts` 绑定到用例的 `pre_script` / `post_script` / `sql_script` 字段）
- **枚举**：`ScriptType`（`pre_script` / `post_script` / `sql_script`，定义于 `app/models/database.py`）

### 10.3 能力 7：SQL 脚本生成

根据自然语言与数据库表结构生成安全 SQL（含建表/查询/造数等），并配套数据库连接管理。

- **Module**：
  - `backend/app/modules/sql_gen/sql_generator.py`（`SQLGenerator.generate`）
  - `backend/app/modules/sql_gen/sql_security.py`（危险语句拦截 / 防注入校验）
- **暴露方式**：复用 `POST /api/scripts/generate`，请求 `script_type=sql_script`
- **依赖 — 数据库连接管理**：`backend/app/api/databases.py`
  - `GET /api/databases/`、`POST /api/databases/`、`GET/PUT/DELETE /api/databases/{conn_id}`
  - `GET /api/databases/{conn_id}/schema`（在线拉取表结构，供 SQL 生成上下文）
  - 模型 `DatabaseConnection`（`database` / `password_encrypted` 字段），Schema `app/schemas/database_conn.py`
- **模型路由**：`model_config` 中 `sql_generation_model_id` 可指定 SQL 生成专用模型

### 10.4 能力 8：定时任务

基于自然语言描述创建定时任务，经 Celery beat 调度触发；支持启停、历史查询。

- **API**：`backend/app/api/scheduled_tasks.py`
  - `GET /api/scheduled-tasks/`、`POST /api/scheduled-tasks/`
  - `POST /api/scheduled-tasks/parse-cron` — 自然语言 → cron 表达式
  - `GET/PUT/DELETE /api/scheduled-tasks/{task_id}`
  - `POST /api/scheduled-tasks/{task_id}/toggle` — 启停
  - `GET /api/scheduled-tasks/{task_id}/history` — 执行历史
- **Schema**：`backend/app/schemas/scheduled_task.py`（`ScheduledTaskCreate` / `ScheduledTaskUpdate` / `ParseCronRequest`；`target_type` 默认 `scenario`，取值 `{scenario, case_collection}`）
- **Module**：`backend/app/modules/scheduler/`
  - `cron_parser.py`（`CronParser`：自然语言 → cron，支持「每天/每周/每月 X 号 X 点」等）
  - `scheduler_service.py`（`SchedulerService`：`list_tasks` / `get_task` / `get_history` / `record_run`，对接 Celery beat）
  - `tasks.py`（Celery 任务 `run_scheduled_task`：触发执行并记录 `ScheduledTaskRun`）
- **枚举**：`ScheduledTaskStatus`（`active` / `paused` / `deleted`）、`ScheduledTaskTargetType`（`scenario` / `case_collection`），定义于 `app/models/database.py`
- **⚠️ 已知降级点**：`tasks.py` 的真实测试执行链（`TestExecutionEngine` / `ScenarioOrchestrator`）需要 `analysis_result` / `test_cases` / `candidate_endpoints` 等完整上下文，而调度上下文仅有 `target_id`，不足以直接拉起一次完整执行。**当前实现为降级记录**：触发时仅写入 `ScheduledTaskRun` 触发记录并标记 `success`，真实执行链待接入（见 10.6）。

### 10.5 能力 9：报告分析

基于测试报告 / 结果进行 AI 分析：失败归因、报告摘要、跨运行对比。

- **API**：`backend/app/api/report_analysis.py`
  - `POST /api/reports/{report_id}/ai-analysis` — 报告智能摘要
  - `POST /api/results/{result_id}/ai-analysis` — 单结果失败归因
  - `POST /api/results/{result_id}/compare` — 与指定运行对比
- **Schema**：`backend/app/schemas/report_analysis.py`（`AnalyzeReportRequest` / `AnalyzeResultRequest` / `CompareRequest`，含 `project_id` / `result_id` / `compare_run_id`）
- **Module**：`backend/app/modules/report_analysis/analyzer.py`（`analyze_failure` / `analyze_summary` / `analyze_compare`）
- **枚举**：`AnalysisType`（`failure` / `report_summary` / `compare`，定义于 `app/models/database.py`）

### 10.6 已知限制与后续 TODO

| 优先级 | 事项 | 说明 |
|--------|------|------|
| **P0** | 定时任务真实执行链 | `modules/scheduler/tasks.py` 当前为降级记录，需接入 `TestExecutionEngine` / `ScenarioOrchestrator` 以真正拉起测试（需补充 `analysis_result` / `test_cases` / `candidate_endpoints` 上下文） |
| P2 | SQL 生成独立 API（可选） | 当前复用 `scripts` 统一入口（`script_type=sql_script`），如需独立鉴权/限流可拆分独立路由 |
| P3 | 能力 5–9 前端联调验证 | `ScriptPanel` / `ScheduledTasks` / `ReportAnalysis` / `DatabaseManage` 页面已建，需在部署环境完成前后端联调回归 |

---

## 附录：项目目录结构

```
ai-test-platform/
├── docker-compose.yml
├── .env.example
├── README.md
│
├── backend/                         # 后端服务
│   ├── app/
│   │   ├── main.py                  # FastAPI 入口
│   │   ├── celery.py                # Celery 配置
│   │   ├── api/                     # API 路由
│   │   │   ├── routes.py
│   │   │   ├── webhook.py           # GitHub/SVN Webhook
│   │   │   ├── source.py            # 统一数据源接入
│   │   │   ├── upload.py            # 文件上传
│   │   │   ├── auth.py
│   │   │   ├── doc.py               # 文档解析/评审（能力1/2）
│   │   │   ├── case_library.py      # 用例生成/采纳（能力3）
│   │   │   ├── scenario.py          # 场景编排（能力4）
│   │   │   ├── scripts.py           # 脚本生成（能力5/6/7 统一入口）
│   │   │   ├── databases.py         # 数据库连接管理（能力7 依赖）
│   │   │   ├── scheduled_tasks.py   # 定时任务（能力8）
│   │   │   └── report_analysis.py   # 报告分析（能力9）
│   │   ├── modules/                 # 核心模块
│   │   │   ├── source/              # 多数据源接入
│   │   │   │   ├── base.py          # 适配器基类+工厂
│   │   │   │   ├── github_adapter.py
│   │   │   │   ├── svn_adapter.py
│   │   │   │   └── upload_adapter.py
│   │   │   ├── code_analyzer/       # AI 代码解析
│   │   │   │   ├── stack_detector.py
│   │   │   │   ├── api_extractor.py
│   │   │   │   ├── ai_analyzer.py
│   │   │   │   └── adapters/        # 各技术栈适配器
│   │   │   ├── ai/                  # AI 模型配置管理
│   │   │   │   ├── model_config.py  # 模型配置数据结构
│   │   │   │   ├── model_client.py  # 统一模型客户端
│   │   │   │   └── model_router.py  # 模型路由器
│   │   │   ├── case_generator/      # AI 用例生成
│   │   │   │   ├── case_generator.py
│   │   │   │   └── coverage_optimizer.py
│   │   │   ├── script_gen/          # 脚本生成（能力5/6）
│   │   │   │   └── script_generator.py
│   │   │   ├── sql_gen/             # SQL 脚本生成（能力7）
│   │   │   │   ├── sql_generator.py
│   │   │   │   └── sql_security.py
│   │   │   ├── scheduler/           # 定时任务（能力8）
│   │   │   │   ├── tasks.py         # Celery 触发任务
│   │   │   │   ├── scheduler_service.py
│   │   │   │   └── cron_parser.py   # 自然语言→cron
│   │   │   ├── report_analysis/     # 报告分析（能力9）
│   │   │   │   └── analyzer.py
│   │   │   ├── execution/           # 测试执行引擎
│   │   │   │   ├── engine.py
│   │   │   │   ├── api_tester.py
│   │   │   │   ├── performance_tester.py
│   │   │   │   ├── integration_tester.py
│   │   │   │   └── env_adapters.py
│   │   │   ├── defect_analyzer.py   # 缺陷智能识别
│   │   │   ├── report/              # 报告生成（在线+PDF）
│   │   │   │   ├── generator.py
│   │   │   │   └── templates/
│   │   │   ├── monitor/             # 容错监控
│   │   │   │   ├── fault_tolerance.py
│   │   │   │   └── checkpoint.py
│   │   │   ├── auth/                # 多租户与RBAC（企业级）
│   │   │   │   └── rbac.py
│   │   │   ├── audit/               # 审计日志（企业级）
│   │   │   │   └── logger.py
│   │   │   ├── security/            # 代码脱敏与数据安全（企业级）
│   │   │   │   └── desensitizer.py
│   │   │   ├── notification/        # 通知与告警（企业级）
│   │   │   │   └── notifier.py
│   │   │   ├── quality_gate/        # 质量门禁（企业级）
│   │   │   │   └── gate.py
│   │   │   └── mock/               # API Mock（企业级）
│   │   │       └── mock_server.py
│   │   ├── models/                  # 数据模型
│   │   ├── config.py                # 配置
│   │   └── utils/                   # 工具函数
│   ├── alembic/                     # 数据库迁移
│   ├── requirements.txt
│   └── Dockerfile
│
├── frontend/                        # 前端服务
│   ├── src/
│   │   ├── views/                   # 页面
│   │   │   ├── Dashboard.vue        # 仪表盘
│   │   │   ├── TestRun.vue          # 测试运行
│   │   │   ├── Report.vue           # 报告查看（在线交互+PDF导出）
│   │   │   ├── QualityTrend.vue     # 质量趋势看板（企业级）
│   │   │   ├── Settings.vue         # 配置
│   │   │   ├── ModelConfig.vue      # AI模型配置（企业级）
│   │   │   ├── SourceManage.vue     # 数据源管理（GitHub/SVN/上传）
│   │   │   ├── QualityGate.vue      # 质量门禁配置（企业级）
│   │   │   ├── ScriptPanel.vue        # 脚本/SQL 生成面板（能力5/6/7）
│   │   │   ├── DatabaseManage.vue     # 数据库连接管理（能力7）
│   │   │   ├── ScheduledTasks.vue     # 定时任务（能力8）
│   │   │   ├── ReportAnalysis.vue     # 报告分析（能力9）
│   │   │   └── AuditLog.vue         # 审计日志（企业级）
│   │   ├── components/              # 组件
│   │   ├── api/                     # API 调用
│   │   ├── stores/                  # Pinia 状态
│   │   └── router/                  # 路由
│   ├── package.json
│   └── Dockerfile
│
├── data/                            # 数据目录
│   ├── repos/                       # 代码仓库
│   └── reports/                     # 测试报告
│
└── docs/                            # 文档
    ├── api.md                       # API 文档
    ├── deployment.md                # 部署文档
    └── extension.md                 # 扩展指南
```

---

*本方案覆盖从架构设计到落地部署的完整链路，所有模块设计均包含具体实现代码，可直接作为开发蓝图使用。V2 版新增：多数据源接入（GitHub/SVN/上传）、AI 模型可配置管理、报告在线交互+PDF 双模式、8 项企业级增强方案（多租户 RBAC、审计日志、代码脱敏、通知集成、质量门禁、趋势看板、环境管理、API Mock）。V3 版新增：九大 AI 能力实现状态矩阵（第十章），以及能力 5–9 对应的脚本/SQL 生成（script_gen / sql_gen）、定时任务（scheduler）、报告分析（report_analysis）模块与对应前端页面；其中定时任务真实执行链为已知降级点（详见 10.4 / 10.6）。*
