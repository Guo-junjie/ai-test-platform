"""
AI 模型配置管理 API 路由

提供：
- GET    /configs               — 列出全部模型配置（API Key 脱敏）
- POST   /configs               — 创建模型配置（API Key 加密存储）
- GET    /configs/{config_id}   — 模型配置详情
- PUT    /configs/{config_id}   — 更新模型配置
- DELETE /configs/{config_id}   — 删除模型配置（自动清理引用它的路由记录）
- POST   /configs/{config_id}/test — 测试模型连通性
- GET    /routing               — 获取模型路由配置
- PUT    /routing               — 更新模型路由配置（upsert）

注意：router 本身不带 prefix，统一由 main.py 以 ``prefix="/api/models"`` 注册。
API Key 采用 app.utils.crypto 的 Fernet 加密落库，任何响应都不会回传明文。
"""

import uuid
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import AIModelConfig, ModelProvider, ModelRouting, User
from app.modules.auth.dependencies import get_current_user, require_admin
from app.utils.crypto import decrypt, encrypt, mask_api_key
from app.utils.database import get_db_session
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter()

# 路由字段名 → 对应的 ModelRouting 列名
ROUTING_FIELDS: tuple[str, ...] = (
    "code_analysis_model_id",
    "case_generation_model_id",
    "defect_analysis_model_id",
    "fix_suggestion_model_id",
    "doc_parse_model_id",
    "doc_review_model_id",
    "scenario_orchestration_model_id",
    "fallback_model_id",
)


# ==================== 请求模型 ====================


class CreateModelConfigRequest(BaseModel):
    """创建模型配置请求"""

    name: str
    provider: str = "openai"  # openai / anthropic / custom / local
    model_name: str
    api_base_url: str
    api_key: str  # 明文，落库前加密
    api_version: str | None = None
    max_tokens: int = 4096
    temperature: float = 0.3
    timeout: int = 120
    max_retries: int = 3
    use_cases: list[str] = Field(default_factory=list)
    is_default: bool = False
    is_fallback: bool = False
    is_active: bool = True


class UpdateModelConfigRequest(BaseModel):
    """更新模型配置请求 — 所有字段可选，仅更新传入项"""

    name: str | None = None
    provider: str | None = None
    model_name: str | None = None
    api_base_url: str | None = None
    api_key: str | None = None  # 传入则重新加密
    api_version: str | None = None
    max_tokens: int | None = None
    temperature: float | None = None
    timeout: int | None = None
    max_retries: int | None = None
    use_cases: list[str] | None = None
    is_default: bool | None = None
    is_fallback: bool | None = None
    is_active: bool | None = None


class UpdateRoutingRequest(BaseModel):
    """更新模型路由请求 — 值为 AIModelConfig.id"""

    code_analysis_model_id: str | None = None
    case_generation_model_id: str | None = None
    defect_analysis_model_id: str | None = None
    fix_suggestion_model_id: str | None = None
    doc_parse_model_id: str | None = None
    doc_review_model_id: str | None = None
    scenario_orchestration_model_id: str | None = None
    fallback_model_id: str | None = None


# ==================== 内部工具 ====================


def _parse_provider(provider: str) -> ModelProvider:
    """
    解析 provider 字符串为 ModelProvider 枚举。

    Raises:
        HTTPException(400): 非法 provider。
    """
    try:
        return ModelProvider(provider.lower())
    except ValueError:
        valid = "/".join(p.value for p in ModelProvider)
        raise HTTPException(400, f"无效的 provider: {provider}。可选: {valid}")


def _masked_api_key(config: AIModelConfig) -> str:
    """解密后脱敏展示 API Key；解密失败返回固定掩码。"""
    if not config.api_key_encrypted:
        return ""
    try:
        return mask_api_key(decrypt(config.api_key_encrypted))
    except ValueError:
        return "********"


def _config_to_dict(config: AIModelConfig) -> dict[str, Any]:
    """将 AIModelConfig 序列化为响应字典（不含明文 API Key）。"""
    return {
        "id": config.id,
        "config_id": config.id,
        "name": config.name,
        "provider": config.provider.value if config.provider else None,
        "api_base_url": config.api_base_url,
        "api_key_masked": _masked_api_key(config),
        "model_name": config.model_name,
        "api_version": config.api_version,
        "max_tokens": config.max_tokens,
        "temperature": config.temperature,
        "timeout": config.timeout,
        "max_retries": config.max_retries,
        "use_cases": config.use_cases or [],
        "is_active": bool(config.is_active),
        "is_default": bool(config.is_default),
        "is_fallback": bool(config.is_fallback),
        "created_at": config.created_at.isoformat() if config.created_at else None,
        "updated_at": config.updated_at.isoformat() if config.updated_at else None,
    }


def _routing_to_dict(routing: ModelRouting | None) -> dict[str, Any]:
    """将 ModelRouting 序列化为响应字典；无记录时返回空默认对象。"""
    if routing is None:
        empty: dict[str, Any] = {field: None for field in ROUTING_FIELDS}
        empty["id"] = None
        empty["updated_at"] = None
        return empty

    data: dict[str, Any] = {field: getattr(routing, field) for field in ROUTING_FIELDS}
    data["id"] = routing.id
    data["updated_at"] = routing.updated_at.isoformat() if routing.updated_at else None
    return data


async def _get_config_or_404(config_id: str, db: AsyncSession) -> AIModelConfig:
    """按 ID 查询模型配置，不存在时抛 404。"""
    result = await db.execute(
        select(AIModelConfig).where(AIModelConfig.id == config_id)
    )
    config = result.scalar_one_or_none()
    if config is None:
        raise HTTPException(404, f"模型配置不存在: {config_id}")
    return config


async def _clear_default_flag(db: AsyncSession, keep_id: str) -> None:
    """确保全局唯一默认模型 — 将其它配置的 is_default 置为 False。"""
    result = await db.execute(
        select(AIModelConfig).where(AIModelConfig.is_default.is_(True))
    )
    for other in result.scalars().all():
        if other.id != keep_id:
            other.is_default = False


async def _clear_fallback_flag(db: AsyncSession, keep_id: str) -> None:
    """确保全局唯一备用模型 — 将其它配置的 is_fallback 置为 False。"""
    result = await db.execute(
        select(AIModelConfig).where(AIModelConfig.is_fallback.is_(True))
    )
    for other in result.scalars().all():
        if other.id != keep_id:
            other.is_fallback = False


async def _load_routing(db: AsyncSession) -> ModelRouting | None:
    """读取唯一一条模型路由记录（按 id 升序取第一条）。"""
    result = await db.execute(select(ModelRouting).order_by(ModelRouting.id).limit(1))
    return result.scalar_one_or_none()


# ==================== 模型配置 CRUD ====================


@router.get("/configs")
async def list_model_configs(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """列出所有模型配置（API Key 已脱敏）。"""
    result = await db.execute(
        select(AIModelConfig).order_by(AIModelConfig.created_at.desc())
    )
    configs = [_config_to_dict(c) for c in result.scalars().all()]

    return {
        "code": 0,
        "data": {"list": configs, "configs": configs, "total": len(configs)},
        "message": "success",
    }


@router.post("/configs")
async def create_model_config(
    req: CreateModelConfigRequest,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session),
):
    """创建模型配置（API Key 加密存储，仅管理员）。"""
    provider = _parse_provider(req.provider)

    if not req.api_key:
        raise HTTPException(400, "api_key 不能为空")

    config_id = uuid.uuid4().hex
    config = AIModelConfig(
        id=config_id,
        name=req.name,
        provider=provider,
        api_base_url=req.api_base_url,
        api_key_encrypted=encrypt(req.api_key),
        model_name=req.model_name,
        api_version=req.api_version,
        max_tokens=req.max_tokens,
        temperature=req.temperature,
        timeout=req.timeout,
        max_retries=req.max_retries,
        use_cases=req.use_cases,
        is_active=req.is_active,
        is_default=req.is_default,
        is_fallback=req.is_fallback,
    )
    db.add(config)

    if req.is_default:
        await _clear_default_flag(db, config_id)
    if req.is_fallback:
        await _clear_fallback_flag(db, config_id)

    await db.flush()
    await db.refresh(config)

    logger.info(f"Model config created: {req.name} ({config_id}) by {current_user.username}")

    return {"code": 0, "data": _config_to_dict(config), "message": "模型配置创建成功"}


@router.get("/configs/{config_id}")
async def get_model_config(
    config_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """获取模型配置详情（API Key 已脱敏）。"""
    config = await _get_config_or_404(config_id, db)
    return {"code": 0, "data": _config_to_dict(config), "message": "success"}


@router.put("/configs/{config_id}")
async def update_model_config(
    config_id: str,
    req: UpdateModelConfigRequest,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session),
):
    """更新模型配置（传入 api_key 时重新加密，仅管理员）。"""
    config = await _get_config_or_404(config_id, db)

    if req.provider is not None:
        config.provider = _parse_provider(req.provider)
    if req.api_key:
        config.api_key_encrypted = encrypt(req.api_key)

    # 简单字段逐项覆盖（None 表示不修改）
    simple_fields = (
        "name",
        "model_name",
        "api_base_url",
        "api_version",
        "max_tokens",
        "temperature",
        "timeout",
        "max_retries",
        "use_cases",
        "is_active",
    )
    for field in simple_fields:
        value = getattr(req, field)
        if value is not None:
            setattr(config, field, value)

    if req.is_default is not None:
        config.is_default = req.is_default
        if req.is_default:
            await _clear_default_flag(db, config_id)
    if req.is_fallback is not None:
        config.is_fallback = req.is_fallback
        if req.is_fallback:
            await _clear_fallback_flag(db, config_id)

    await db.flush()
    await db.refresh(config)

    logger.info(f"Model config updated: {config_id} by {current_user.username}")

    return {"code": 0, "data": _config_to_dict(config), "message": "模型配置更新成功"}


@router.delete("/configs/{config_id}")
async def delete_model_config(
    config_id: str,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session),
):
    """
    删除模型配置（仅管理员）。

    ModelRouting 的五个外键列均为 NOT NULL，无法置空，
    因此若存在引用该配置的路由记录，先删除路由记录再删配置，避免 FK 报错。
    """
    config = await _get_config_or_404(config_id, db)

    routing = await _load_routing(db)
    routing_cleared = False
    if routing is not None and any(
        getattr(routing, field) == config_id for field in ROUTING_FIELDS
    ):
        await db.delete(routing)
        routing_cleared = True
        logger.warning(
            f"Model routing removed because it referenced deleted config {config_id}"
        )

    await db.delete(config)
    await db.flush()

    logger.info(f"Model config deleted: {config_id} by {current_user.username}")

    return {
        "code": 0,
        "data": {"id": config_id, "routing_cleared": routing_cleared},
        "message": "模型配置删除成功",
    }


# ==================== 连通性测试 ====================


@router.post("/configs/{config_id}/test")
async def test_model_connection(
    config_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """
    测试模型连通性 — 对 api_base_url 发起轻量探活请求。

    OpenAI 兼容接口探测 ``GET {base}/models``；其它 provider 直接 GET base_url。
    只要拿到 HTTP 响应且状态码非 401/403 即视为可达。
    """
    config = await _get_config_or_404(config_id, db)

    try:
        api_key = decrypt(config.api_key_encrypted)
    except ValueError:
        raise HTTPException(400, "API Key 解密失败，请重新保存该配置的 API Key")

    base_url = (config.api_base_url or "").rstrip("/")
    if not base_url:
        raise HTTPException(400, "api_base_url 未配置")

    provider = config.provider.value if config.provider else "custom"
    if provider == "anthropic":
        probe_url = f"{base_url}/v1/models" if not base_url.endswith("/v1") else f"{base_url}/models"
        headers = {
            "x-api-key": api_key,
            "anthropic-version": config.api_version or "2023-06-01",
        }
    elif provider in ("openai", "local"):
        probe_url = f"{base_url}/models"
        headers = {"Authorization": f"Bearer {api_key}"}
    else:
        probe_url = base_url
        headers = {"Authorization": f"Bearer {api_key}"}

    timeout = min(config.timeout or 15, 15)

    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            response = await client.get(probe_url, headers=headers)
    except httpx.TimeoutException:
        return {
            "code": 1,
            "data": {"reachable": False, "probe_url": probe_url},
            "message": f"连接超时（{timeout}s），请检查 api_base_url 或网络",
        }
    except httpx.HTTPError as e:
        return {
            "code": 1,
            "data": {"reachable": False, "probe_url": probe_url},
            "message": f"连接失败: {e}",
        }

    if response.status_code in (401, 403):
        return {
            "code": 1,
            "data": {
                "reachable": True,
                "status_code": response.status_code,
                "probe_url": probe_url,
            },
            "message": "服务可达，但 API Key 鉴权失败，请检查密钥",
        }

    ok = response.status_code < 500

    logger.info(
        f"Model connection test: {config_id} -> {probe_url} "
        f"status={response.status_code} ok={ok}"
    )

    return {
        "code": 0 if ok else 1,
        "data": {
            "reachable": True,
            "status_code": response.status_code,
            "probe_url": probe_url,
            "model_name": config.model_name,
        },
        "message": "连接成功" if ok else f"服务返回异常状态码: {response.status_code}",
    }


# ==================== 模型路由 ====================


@router.get("/routing")
async def get_model_routing(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """获取当前模型路由配置；无记录时返回各字段为 None 的默认空对象。"""
    routing = await _load_routing(db)
    return {"code": 0, "data": _routing_to_dict(routing), "message": "success"}


@router.put("/routing")
async def update_model_routing(
    req: UpdateRoutingRequest,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session),
):
    """
    更新模型路由配置（upsert，仅管理员）。

    - 已有记录：仅覆盖请求中非 None 的字段。
    - 无记录：五个字段均为 NOT NULL，缺失项用「请求中第一个非空值」补齐；
      若请求全为空则返回 400。
    """
    provided = {
        field: getattr(req, field)
        for field in ROUTING_FIELDS
        if getattr(req, field) is not None
    }

    if not provided:
        raise HTTPException(400, "至少需要提供一个模型路由字段")

    # 校验引用的模型配置均存在
    for field, cfg_id in provided.items():
        exists = await db.execute(
            select(AIModelConfig.id).where(AIModelConfig.id == cfg_id)
        )
        if exists.scalar_one_or_none() is None:
            raise HTTPException(400, f"{field} 指向的模型配置不存在: {cfg_id}")

    routing = await _load_routing(db)

    if routing is None:
        # 新建：用第一个提供的值补齐缺失字段，满足 NOT NULL 约束
        default_id = next(iter(provided.values()))
        routing = ModelRouting(
            **{field: provided.get(field, default_id) for field in ROUTING_FIELDS}
        )
        db.add(routing)
        logger.info(f"Model routing created by {current_user.username}")
    else:
        for field, cfg_id in provided.items():
            setattr(routing, field, cfg_id)
        logger.info(f"Model routing updated by {current_user.username}")

    await db.flush()
    await db.refresh(routing)

    return {"code": 0, "data": _routing_to_dict(routing), "message": "模型路由更新成功"}
