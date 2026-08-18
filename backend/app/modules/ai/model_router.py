"""
模型路由器 — 按使用场景路由到不同 AI 模型，主模型失败自动切换备用
"""

from loguru import logger
from typing import Optional

from app.modules.ai.model_config import ModelConfig, ModelRoutingConfig, ModelProvider
from app.modules.ai.model_client import UnifiedModelClient
from app.config import settings


class ModelRouter:
    """
    模型路由器

    按使用场景（代码解析/用例生成/缺陷分析/修复建议）路由到不同模型。
    主模型失败时自动切换到备用模型。
    """

    def __init__(self):
        self.configs: dict[str, ModelConfig] = {}
        self.routing: ModelRoutingConfig = ModelRoutingConfig()
        self._clients: dict[str, UnifiedModelClient] = {}

    def register_config(self, config: ModelConfig):
        """注册模型配置"""
        self.configs[config.config_id] = config
        # 清除已缓存的客户端
        if config.config_id in self._clients:
            del self._clients[config.config_id]
        logger.info(f"Registered model config: {config.name} ({config.config_id})")

    def set_routing(self, routing: ModelRoutingConfig):
        """设置模型路由"""
        self.routing = routing
        logger.info("Model routing updated")

    def get_client(self, use_case: str) -> UnifiedModelClient:
        """获取指定场景的模型客户端"""
        config_id_map = {
            "code_analysis": self.routing.code_analysis_model_id,
            "case_generation": self.routing.case_generation_model_id,
            "defect_analysis": self.routing.defect_analysis_model_id,
            "fix_suggestion": self.routing.fix_suggestion_model_id,
            # 能力1/2：未单独配置时降级到已有插槽，避免 DB 列为 NULL 时抛 ValueError
            "doc_parse": self.routing.doc_parse_model_id or self.routing.code_analysis_model_id,
            "doc_review": self.routing.doc_review_model_id or self.routing.fallback_model_id,
            # 能力4：AI 编排测试场景；未单独配置时降级到 code_analysis 插槽，避免 DB 列 NULL 抛 500
            "scenario_orchestration": self.routing.scenario_orchestration_model_id or self.routing.code_analysis_model_id,
        }

        config_id = config_id_map.get(use_case)
        if not config_id:
            raise ValueError(f"Unknown use case: {use_case}")

        config = self.configs.get(config_id)
        if not config or not config.is_active:
            logger.warning(f"Model {config_id} not available, falling back")
            config = self.configs.get(self.routing.fallback_model_id)
            if not config:
                raise RuntimeError("No available model configuration")

        if config_id not in self._clients:
            self._clients[config_id] = UnifiedModelClient(config)

        return self._clients[config_id]

    async def call(
        self,
        use_case: str,
        messages: list[dict],
        **kwargs,
    ) -> str:
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


# 全局单例
_router: Optional[ModelRouter] = None


def get_model_router() -> ModelRouter:
    """获取全局模型路由器单例"""
    global _router
    if _router is None:
        _router = ModelRouter()
    return _router


async def init_default_models():
    """
    初始化默认 AI 模型配置
    从环境变量读取默认配置，注册到路由器
    """
    router = get_model_router()

    # 默认模型（OpenAI 兼容）
    if settings.OPENAI_API_KEY:
        default_config = ModelConfig(
            config_id="default",
            name=f"默认模型 ({settings.OPENAI_MODEL_NAME})",
            provider=ModelProvider.OPENAI,
            api_base_url=settings.OPENAI_API_BASE,
            api_key=settings.OPENAI_API_KEY,
            model_name=settings.OPENAI_MODEL_NAME,
            is_default=True,
            use_cases=["code_analysis", "case_generation", "defect_analysis", "fix_suggestion", "doc_parse", "doc_review", "scenario_orchestration"],
        )
        router.register_config(default_config)

    # 备用模型（Anthropic）
    if settings.ANTHROPIC_API_KEY:
        fallback_config = ModelConfig(
            config_id="anthropic_fallback",
            name=f"Claude 备用模型 ({settings.ANTHROPIC_MODEL_NAME})",
            provider=ModelProvider.ANTHROPIC,
            api_base_url=settings.ANTHROPIC_API_BASE,
            api_key=settings.ANTHROPIC_API_KEY,
            model_name=settings.ANTHROPIC_MODEL_NAME,
            is_fallback=True,
            use_cases=["code_analysis", "case_generation", "defect_analysis", "fix_suggestion", "doc_parse", "doc_review", "scenario_orchestration"],
        )
        router.register_config(fallback_config)
        router.routing.fallback_model_id = "anthropic_fallback"
    elif settings.OPENAI_API_KEY:
        # 如果没有 Anthropic，使用 OpenAI 作为备用
        router.routing.fallback_model_id = "default"

    # 自定义模型
    if settings.CUSTOM_MODEL_API_BASE and settings.CUSTOM_MODEL_API_KEY:
        custom_config = ModelConfig(
            config_id="custom",
            name=f"自定义模型 ({settings.CUSTOM_MODEL_NAME})",
            provider=ModelProvider.CUSTOM,
            api_base_url=settings.CUSTOM_MODEL_API_BASE,
            api_key=settings.CUSTOM_MODEL_API_KEY,
            model_name=settings.CUSTOM_MODEL_NAME,
            use_cases=["code_analysis", "case_generation"],
        )
        router.register_config(custom_config)

    # 设置路由
    if settings.OPENAI_API_KEY:
        router.set_routing(ModelRoutingConfig(
            code_analysis_model_id="default",
            case_generation_model_id="default",
            defect_analysis_model_id="default",
            fix_suggestion_model_id="default",
            doc_parse_model_id="default",
            doc_review_model_id="default",
            scenario_orchestration_model_id="default",
            fallback_model_id="anthropic_fallback" if settings.ANTHROPIC_API_KEY else "default",
        ))

    logger.info(
        f"Model router initialized with {len(router.configs)} config(s): "
        f"{list(router.configs.keys())}"
    )
