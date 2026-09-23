"""默认认证、角色动作边界与请求引用授权；公开入口必须精确列出。"""
import json
from uuid import UUID

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select

from app.models import database as m
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.project_scope import ADMIN_ROLES, load_project_scope
from app.utils.database import get_db_session

PUBLIC_ROUTES = {
    ("POST", "/api/auth/login"),
    ("GET", "/api/health"),
    ("GET", "/api/reports/static/echarts.min.js"),
}
# These handlers authenticate their own signed credentials; they are not anonymous business APIs.
CREDENTIAL_ROUTES = {
    ("POST", "/api/webhook/github"),
    ("POST", "/api/webhook/trigger"),
    ("GET", "/api/webhook/ci-result/{run_id}"),
    ("GET", "/api/reports/{run_id}/share-view"),
}
REFERENCES = {
    "project_id": m.Project, "test_run_id": m.TestRun, "run_id": m.TestRun,
    "plan_id": m.TestPlan, "case_id": m.TestCaseAsset, "case_asset_id": m.TestCaseAsset,
    "endpoint_id": m.ApiEndpoint, "scenario_id": m.Scenario,
    "result_id": m.TestResult, "test_result_id": m.TestResult,
    "baseline_result_id": m.TestResult, "compare_result_id": m.TestResult,
    "compare_run_id": m.TestRun,
    "environment_profile_id": m.EnvironmentProfile, "env_id": m.EnvironmentProfile,
    "environment_revision_id": m.EnvironmentProfileRevision,
    "plan_revision_id": m.TestPlanRevision, "revision_id": m.TestPlanRevision,
    "conn_id": m.DatabaseConnection, "connection_id": m.DatabaseConnection,
    "defect_id": m.Defect, "task_id": m.ScheduledTask,
    "conversation_id": m.KnowledgeConversation, "message_id": m.KnowledgeMessage,
    "review_id": m.DocReview,
}


def is_personal_action(path):
    return (path.startswith("/api/auth/me") or path == "/api/auth/logout"
            or path.startswith("/api/notifications")
            or path.startswith("/api/knowledge/conversations")
            or path in {"/api/knowledge/ask", "/api/knowledge/search", "/api/knowledge/feedback"})


def enforce_role(user, method, path):
    admin = user.role in ADMIN_ROLES
    if user.role == m.UserRole.AUDITOR:
        auditor_routes = (
            path.startswith("/api/audit")
            or path.startswith("/api/notifications")
            or path.startswith("/api/auth/me")
            or path == "/api/auth/logout"
        )
        if not auditor_routes:
            raise HTTPException(403, "合规审计账号仅可访问审计日志和个人功能")
        return
    # 历史审批单仅供超级管理员收尾；合规审计员保持全局只读。
    if path.startswith("/api/change-requests"):
        if user.role != m.UserRole.SUPER_ADMIN:
            raise HTTPException(403, "历史变更审批仅限超级管理员")
        return
    if path.startswith(("/api/models", "/api/settings", "/api/source", "/api/analysis")):
        if not admin:
            raise HTTPException(403, "此功能仅限管理员")
    if path.startswith("/api/audit") and not admin:
        raise HTTPException(403, "审计日志仅限管理员和审核员")
    if path in {"/api/knowledge/rebuild", "/api/knowledge/reset", "/api/knowledge/config"} or (
        path.startswith("/api/knowledge/terms") and method not in {"GET", "HEAD"}
    ):
        if not admin:
            raise HTTPException(403, "全局知识配置仅限管理员")
    if method == "POST" and path in {"/api/test-runs", "/api/webhook/svn", "/api/upload"} and not admin:
        raise HTTPException(403, "原始代码执行和接入仅限管理员，请使用项目测试计划")
    mutation = method not in {"GET", "HEAD", "OPTIONS"} or path.endswith("/share")
    if mutation and path.startswith("/api/scheduled-tasks") and user.role not in (
        ADMIN_ROLES | {m.UserRole.TEST_MANAGER, m.UserRole.TESTER}
    ):
        raise HTTPException(403, "定时测试操作仅限测试人员或管理员")
    if mutation and not is_personal_action(path) and user.role in {m.UserRole.VIEWER, m.UserRole.AUDITOR}:
        raise HTTPException(403, "当前角色没有业务资源写入或执行权限")


def reference_model(key, path):
    if key == "doc_id":
        return (m.RequirementDoc if path.startswith("/api/requirements") else
                m.KnowledgeDocument if path.startswith("/api/knowledge") else m.InterfaceDoc)
    if key == "report_id":
        return m.CoverageReport if path.startswith("/api/coverage") else m.TestReport
    if key == "source_id":
        return m.Project
    return REFERENCES.get(key)


async def authorize_request(request: Request, db=Depends(get_db_session)):
    route = request.scope.get("route")
    path = getattr(route, "path", request.url.path)
    method = request.method
    if (method, path) in PUBLIC_ROUTES | CREDENTIAL_ROUTES:
        return
    user = await get_current_user(request, db)
    request.state.current_user = user
    enforce_role(user, method, path)
    if user.role in ADMIN_ROLES:
        return
    scope = await load_project_scope(db, user)
    db.info["project_scope"] = scope
    request.state.project_scope = scope
    payload = {}
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        try:
            data = await request.json()
            if isinstance(data, dict):
                payload = data
        except (ValueError, json.JSONDecodeError):
            pass  # FastAPI returns the body validation error.
    elif "multipart/form-data" in content_type:
        payload = dict(await request.form())
    mutation = method not in {"GET", "HEAD", "OPTIONS"} or path.endswith("/share")
    write = mutation and not is_personal_action(path)

    async def check(key, value):
        model = reference_model(key, path)
        if model is None or value in (None, ""):
            return
        try:
            resource_id = UUID(str(value))
        except ValueError:
            raise HTTPException(422, f"无效的 {key}")
        if model is m.Project:
            allowed = scope.writable_ids if write else scope.project_ids
            if resource_id not in allowed:
                raise HTTPException(403, "没有此项目的访问权限")
        result = (await db.execute(select(model).where(model.id == resource_id))).scalar_one_or_none()
        if result is None:
            raise HTTPException(404, "资源不存在或无权访问")
        if write:
            from app.modules.auth.project_scope import table_predicate
            predicate = table_predicate(model.__table__, scope, write=True)
            if predicate is not None and (await db.execute(select(model).where(
                model.id == resource_id, predicate
            ))).scalar_one_or_none() is None:
                raise HTTPException(403, "没有此资源的写入权限")

    # Validate path and query separately from body: a body must never shadow a path ID.
    for source in (request.query_params, request.path_params, payload):
        for key, value in source.items():
            await check(key, value)
        for key, single in {"case_ids": "case_id", "endpoint_ids": "endpoint_id"}.items():
            for value in source.get(key, []) or []:
                await check(single, value)
    for config_key in ("target_config", "env_config", "context"):
        config = payload.get(config_key)
        if isinstance(config, dict):
            for key, value in config.items():
                await check(key, value)
            for value in config.get("asset_ids", []) or []:
                await check("case_id", value)
    if payload.get("target_id"):
        target_type = payload.get("target_type")
        if not target_type and request.path_params.get("task_id"):
            task = await db.get(m.ScheduledTask, UUID(request.path_params["task_id"]))
            target_type = task.target_type.value if hasattr(task.target_type, "value") else task.target_type
        key = {"plan": "plan_id", "scenario": "scenario_id"}.get(target_type)
        if not key:
            raise HTTPException(422, "无法确认定时任务目标类型")
        await check(key, payload["target_id"])
