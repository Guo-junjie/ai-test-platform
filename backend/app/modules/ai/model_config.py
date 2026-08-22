"""
AI 模型配置数据结构
"""

from pydantic import BaseModel
from enum import Enum
from typing import Optional


class ModelProvider(str, Enum):
    """模型提供商类型"""
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    CUSTOM = "custom"
    LOCAL = "local"


class ModelConfig(BaseModel):
    """单个 AI 模型配置"""

    config_id: str
    name: str
    provider: ModelProvider = ModelProvider.OPENAI

    api_base_url: str = "https://api.openai.com/v1"
    api_key: str = ""
    model_name: str = "gpt-4o"

    api_version: Optional[str] = None
    max_tokens: int = 4096
    temperature: float = 0.3
    timeout: int = 120
    max_retries: int = 3

    use_cases: list[str] = []
    is_active: bool = True
    is_default: bool = False
    is_fallback: bool = False


class ModelRoutingConfig(BaseModel):
    """模型路由配置 — 按使用场景分配模型"""

    code_analysis_model_id: str = "default"
    case_generation_model_id: str = "default"
    defect_analysis_model_id: str = "default"
    fix_suggestion_model_id: str = "default"
    # 能力1：AI 解析接口文档（文本 → 结构化接口定义）
    doc_parse_model_id: str = "default"
    # 能力2：AI 评审接口文档（接口定义 → 多维质检评分）
    doc_review_model_id: str = "default"
    # 能力4：AI 编排测试场景（自然语言 → 结构化多步串联）
    scenario_orchestration_model_id: str = "default"
    # 能力5/6/7：AI 脚本生成（pre/post/sql）
    script_generation_model_id: str = "default"
    # 能力7：AI SQL 生成
    sql_generation_model_id: str = "default"
    # 能力9：AI 报告分析（失败分析/摘要/对比）
    report_analysis_model_id: str = "default"
    # 能力12：嵌入模型插槽（未单独配置时降级到 fallback）
    embedding_model_id: str = "default"
    fallback_model_id: str = "default"
