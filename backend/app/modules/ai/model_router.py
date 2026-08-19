"""
模型路由器 — 按使用场景路由到不同 AI 模型，主模型失败自动切换备用
"""

from loguru import logger
from typing import Optional

from app.modules.ai.model_config import ModelConfig, ModelRoutingConfig, ModelProvider
from app.modules.ai.model_client import UnifiedModelClient


class ModelNotConfiguredError(RuntimeError):
    """模型未配置异常。

    当某个 use_case 没有任何可用（已启用）的模型配置时由 ModelRouter 抛出。
    全局异常处理器会将其转为 HTTP 409，并携带 ``code=MODEL_NOT_CONFIGURED``，
    前端据此弹出「去配置模型」引导，而不是返回一个误导性的 fallback 结果。
    """


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
            # 能力5/6/7：脚本生成；未单独配置时降级到 case_generation 插槽
            "script_generation": self.routing.script_generation_model_id or self.routing.case_generation_model_id,
            # 能力7：SQL 生成；未单独配置时降级到 case_generation 插槽
            "sql_generation": self.routing.sql_generation_model_id or self.routing.case_generation_model_id,
            # 能力9：报告分析；未单独配置时降级到 fallback 插槽
            "report_analysis": self.routing.report_analysis_model_id or self.routing.fallback_model_id,
        }

        config_id = config_id_map.get(use_case)
        if not config_id:
            raise ValueError(f"Unknown use case: {use_case}")

        config = self.configs.get(config_id)
        if not config or not config.is_active:
            logger.warning(f"Model {config_id} not available, falling back")
            config = self.configs.get(self.routing.fallback_model_id)
            if not config:
                raise ModelNotConfiguredError(
                    "尚未配置 AI 模型，请先在「AI 模型配置」页面添加并启用至少一个模型后再使用此功能。"
                )

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


async def refresh_model_router_from_db(db) -> None:
    """
    从数据库加载模型配置与路由到内存路由器（唯一真相源）。

    - 读取全部 ``AIModelConfig`` → 解密 api_key 后注册为 :class:`ModelConfig`。
    - 读取唯一一条 ``ModelRouting`` 记录 → 设为路由；若无记录但存在启用模型，
      则将所有 use_case 路由到第一个启用模型（「配一个即用」）。
    - 调用时机：应用启动、以及模型配置 / 路由发生增删改之后。

    注意：``app.models.database`` 与 ``app.utils.crypto`` 采用惰性导入，
    避免与模型定义 / 加解密模块形成导入环。
    """
    from app.models.database import AIModelConfig, ModelRouting
    from app.utils.crypto import decrypt
    from sqlalchemy import select

    router = get_model_router()

    result = await db.execute(select(AIModelConfig))
    rows = result.scalars().all()

    router.configs.clear()
    for c in rows:
        try:
            api_key = decrypt(c.api_key_encrypted) if c.api_key_encrypted else ""
        except Exception:
            api_key = ""
        cfg = ModelConfig(
            config_id=c.id,
            name=c.name,
            provider=c.provider,
            api_base_url=c.api_base_url or "",
            api_key=api_key,
            model_name=c.model_name or "",
            api_version=c.api_version,
            max_tokens=c.max_tokens or 4096,
            temperature=c.temperature if c.temperature is not None else 0.3,
            timeout=c.timeout or 120,
            max_retries=c.max_retries or 3,
            use_cases=list(c.use_cases or []),
            is_active=bool(c.is_active),
            is_default=bool(c.is_default),
            is_fallback=bool(c.is_fallback),
        )
        router.register_config(cfg)

    rresult = await db.execute(
        select(ModelRouting).order_by(ModelRouting.id).limit(1)
    )
    routing_row = rresult.scalar_one_or_none()
    routing_fields = list(ModelRoutingConfig.model_fields.keys())
    if routing_row is not None:
        router.set_routing(
            ModelRoutingConfig(
                **{f: getattr(routing_row, f) for f in routing_fields}
            )
        )
    else:
        # 无路由记录：若有启用模型，全部路由到第一个启用模型，保证「配一个即用」
        first_active = next((c.id for c in rows if c.is_active), None)
        if first_active:
            router.set_routing(
                ModelRoutingConfig(**{f: first_active for f in routing_fields})
            )

    logger.info(
        f"Model router refreshed from DB: {len(router.configs)} config(s), "
        f"routing={'set' if router.routing else 'empty'}"
    )


async def init_default_models() -> None:
    """
    初始化模型路由器：从数据库加载已配置的模型。

    **出厂默认即为空** —— 不再从环境变量自动播种模型。
    未配置模型时调用任何 AI 功能都会抛出 :class:`ModelNotConfiguredError`
    （HTTP 409），并提示用户先在「AI 模型配置」页面配置模型。
    """
    from app.utils.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        await refresh_model_router_from_db(db)
