"""
能力4（AI 编排测试场景）API。

统一返回 {"code": 0, "data": ..., "message": "..."}。
router 不带 prefix，由 main.py 以 prefix="/api/scenarios" 注册。

⚠️ 路由声明顺序（关键，否则被 UUID 路由吞掉）：
    /dry-run（顶层，取 nl_input+project_id）必须声明在 /{id} 之前；
    / 与 /{id} 段数不同不会冲突，但仍按 create/list 先于 detail 声明。
"""

import re
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from app.models.database import (
    Project,
    Scenario,
    ScenarioStatus,
    User,
)
from app.modules.auth.dependencies import get_current_user
from app.modules.scenario import EndpointRetriever, ScenarioOrchestrator
from app.schemas.scenario import (
    CreateScenarioRequest,
    DryRunRequest,
    UpdateScenarioRequest,
)
from app.utils.database import get_db_session
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter()


# ==================== 序列化与工具 ====================


def _scenario_to_dict(scenario: Scenario, engine: str | None = None) -> dict[str, Any]:
    """将场景行序列化为响应字典。"""
    return {
        "id": str(scenario.id),
        "project_id": str(scenario.project_id),
        "name": scenario.name,
        "description": scenario.description,
        "nl_input": scenario.nl_input,
        "status": scenario.status.value if scenario.status else None,
        "steps": scenario.steps or [],
        "engine": engine,
        "created_by": str(scenario.created_by) if scenario.created_by else None,
        "created_at": scenario.created_at.isoformat() if scenario.created_at else None,
        "updated_at": scenario.updated_at.isoformat() if scenario.updated_at else None,
    }


def _default_name(nl_input: str) -> str:
    """由自然语言输入生成默认场景名（截断）。"""
    text = (nl_input or "").strip().replace("\n", " ")
    if not text:
        return "未命名场景"
    return (text[:30] + "…") if len(text) > 30 else text


def _restrict_candidates(candidates: list[dict], endpoint_ids: list[str]) -> list[dict]:
    """若显式指定接口，则仅保留这些候选（保持原排序/打分）。"""
    if not endpoint_ids:
        return candidates
    id_set = set()
    for sid in endpoint_ids:
        try:
            id_set.add(str(uuid.UUID(sid)))
        except ValueError:
            continue
    if not id_set:
        return candidates
    filtered = [c for c in candidates if c.get("id") in id_set]
    return filtered or candidates


def _resolve_templates(obj: Any, extracted: dict[str, str]) -> Any:
    """递归把 {{var}} 占位符替换为标注来源的文本（预览用）。"""
    if isinstance(obj, str):
        def repl(m: "re.Match") -> str:
            var = m.group(1)
            if var in extracted:
                return f"${{{var}}}<-({extracted[var]})"
            return m.group(0)

        return re.sub(r"\{\{(\w+)\}\}", repl, obj)
    if isinstance(obj, dict):
        return {k: _resolve_templates(v, extracted) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_resolve_templates(v, extracted) for v in obj]
    return obj


def _build_preview(steps: list[dict]) -> list[dict]:
    """根据各步 extract 串联替换后续 {{var}}，产出预览请求序列。"""
    extracted: dict[str, str] = {}
    preview: list[dict] = []
    for step in steps:
        for var, path in (step.get("extract") or {}).items():
            extracted[var] = path
        req = step.get("request") or {}
        preview.append(
            {
                "step_order": step.get("step_order"),
                "method": step.get("method"),
                "url": step.get("url"),
                "request": {
                    "headers": _resolve_templates(req.get("headers", {}) or {}, extracted),
                    "body": _resolve_templates(req.get("body", {}) or {}, extracted),
                    "params": _resolve_templates(req.get("params", {}) or {}, extracted),
                },
                "depends_on_step": step.get("depend_on_step"),
            }
        )
    return preview


# ==================== 端点（注意声明顺序） ====================


@router.post("/")
async def create_scenario(
    req: CreateScenarioRequest,
    current_user: User = Depends(get_current_user),
    db=Depends(get_db_session),
):
    """创建场景：检索候选接口 → AI 编排 → 落库（status=ORCHESTRATED）。"""
    try:
        pid = uuid.UUID(req.project_id)
    except ValueError:
        raise HTTPException(400, "invalid project_id")

    proj = (
        await db.execute(select(Project).where(Project.id == pid))
    ).scalar_one_or_none()
    if proj is None:
        raise HTTPException(404, "project not found")

    if not req.nl_input or not req.nl_input.strip():
        raise HTTPException(400, "nl_input is required")

    retriever = EndpointRetriever()
    candidates = await retriever.search(req.nl_input, pid, db)
    candidates = _restrict_candidates(candidates, req.endpoint_ids or [])

    orchestrator = ScenarioOrchestrator()
    result = await orchestrator.orchestrate(
        nl_input=req.nl_input, project_id=pid, candidate_endpoints=candidates, db=db
    )

    scenario = Scenario(
        id=uuid.uuid4(),
        project_id=pid,
        name=req.name or _default_name(req.nl_input),
        description=None,
        nl_input=req.nl_input,
        status=ScenarioStatus.ORCHESTRATED,
        steps=result["steps"],
        created_by=current_user.id,
    )
    db.add(scenario)
    await db.flush()
    await db.refresh(scenario)

    return {
        "code": 0,
        "data": _scenario_to_dict(scenario, engine=result["engine"]),
        "message": "created",
    }


@router.get("/")
async def list_scenarios(
    project_id: str,
    status: str | None = None,
    keyword: str | None = None,
    page: int = 1,
    page_size: int = 20,
    current_user: User = Depends(get_current_user),
    db=Depends(get_db_session),
):
    """场景列表，project_id 必填，可选 status / keyword。"""
    try:
        pid = uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(400, "invalid project_id")

    q = select(Scenario).where(Scenario.project_id == pid)
    if status:
        try:
            q = q.where(Scenario.status == ScenarioStatus(status))
        except ValueError:
            pass
    if keyword:
        like = f"%{keyword}%"
        q = q.where(
            (Scenario.name.ilike(like)) | (Scenario.nl_input.ilike(like))
        )

    all_rows = (await db.execute(q.order_by(Scenario.created_at.desc()))).scalars().all()
    total = len(all_rows)
    page = max(1, page)
    page_size = max(1, min(page_size, 200))
    start = (page - 1) * page_size
    items = all_rows[start : start + page_size]

    return {
        "code": 0,
        "data": {
            "total": total,
            "page": page,
            "page_size": page_size,
            "items": [_scenario_to_dict(s) for s in items],
        },
        "message": "success",
    }


@router.post("/dry-run")
async def dry_run_scenario(
    req: DryRunRequest,
    current_user: User = Depends(get_current_user),
    db=Depends(get_db_session),
):
    """场景预览：检索 + 编排，返回解析后的请求序列（engine=preview），不落库、不接真实 HTTP。"""
    try:
        pid = uuid.UUID(req.project_id)
    except ValueError:
        raise HTTPException(400, "invalid project_id")

    proj = (
        await db.execute(select(Project).where(Project.id == pid))
    ).scalar_one_or_none()
    if proj is None:
        raise HTTPException(404, "project not found")

    if not req.nl_input or not req.nl_input.strip():
        raise HTTPException(400, "nl_input is required")

    retriever = EndpointRetriever()
    candidates = await retriever.search(req.nl_input, pid, db)
    candidates = _restrict_candidates(candidates, req.endpoint_ids or [])

    orchestrator = ScenarioOrchestrator()
    result = await orchestrator.orchestrate(
        nl_input=req.nl_input, project_id=pid, candidate_endpoints=candidates, db=db
    )

    preview = _build_preview(result["steps"])

    return {
        "code": 0,
        "data": {
            "engine": "preview",
            "source_engine": result["engine"],  # 底层是 ai 还是 rule 兜底
            "steps": result["steps"],
            "preview_requests": preview,
            "candidate_count": len(candidates),
            "note": "MVP 未接真实 HTTP 执行，仅返回编排后的请求序列预览",
        },
        "message": "preview",
    }


@router.get("/{scenario_id}")
async def get_scenario(
    scenario_id: str,
    current_user: User = Depends(get_current_user),
    db=Depends(get_db_session),
):
    """场景详情（含 steps）。"""
    try:
        sid = uuid.UUID(scenario_id)
    except ValueError:
        raise HTTPException(400, "invalid scenario_id")
    scenario = (
        await db.execute(select(Scenario).where(Scenario.id == sid))
    ).scalar_one_or_none()
    if scenario is None:
        raise HTTPException(404, "scenario not found")
    return {
        "code": 0,
        "data": _scenario_to_dict(scenario),
        "message": "success",
    }


@router.put("/{scenario_id}")
async def update_scenario(
    scenario_id: str,
    req: UpdateScenarioRequest,
    current_user: User = Depends(get_current_user),
    db=Depends(get_db_session),
):
    """编辑场景（名称/描述/输入/步骤）。status 不由此接口变更。"""
    try:
        sid = uuid.UUID(scenario_id)
    except ValueError:
        raise HTTPException(400, "invalid scenario_id")
    scenario = (
        await db.execute(select(Scenario).where(Scenario.id == sid))
    ).scalar_one_or_none()
    if scenario is None:
        raise HTTPException(404, "scenario not found")

    if req.name is not None:
        scenario.name = req.name
    if req.description is not None:
        scenario.description = req.description
    if req.nl_input is not None:
        scenario.nl_input = req.nl_input
    if req.steps is not None:
        scenario.steps = req.steps

    await db.flush()
    await db.refresh(scenario)

    return {
        "code": 0,
        "data": _scenario_to_dict(scenario),
        "message": "updated",
    }


@router.post("/{scenario_id}/adopt")
async def adopt_scenario(
    scenario_id: str,
    current_user: User = Depends(get_current_user),
    db=Depends(get_db_session),
):
    """接纳场景（status -> ADOPTED）。"""
    try:
        sid = uuid.UUID(scenario_id)
    except ValueError:
        raise HTTPException(400, "invalid scenario_id")
    scenario = (
        await db.execute(select(Scenario).where(Scenario.id == sid))
    ).scalar_one_or_none()
    if scenario is None:
        raise HTTPException(404, "scenario not found")

    scenario.status = ScenarioStatus.ADOPTED
    await db.flush()
    await db.refresh(scenario)

    return {
        "code": 0,
        "data": _scenario_to_dict(scenario),
        "message": "adopted",
    }
