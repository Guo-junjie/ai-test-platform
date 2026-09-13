"""测试计划用例的发布时内容指纹与可执行快照。"""

import hashlib
import json
from copy import deepcopy
from typing import Any

from app.models.database import TestCaseAsset


def case_content_hash(asset: TestCaseAsset | None) -> str:
    """保持与历史修订版一致的指纹格式，以便校验旧数据。"""
    if asset is None:
        return "deleted"
    content = {
        "title": asset.title,
        "request_data": asset.request_data or {},
        "expected_result": asset.expected_result or {},
        "priority": asset.priority,
        "case_type": asset.case_type,
    }
    raw = json.dumps(content, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def executable_case_payload(asset: TestCaseAsset) -> dict[str, Any]:
    """同时满足执行器的 request/expected 与结果入库的字段约定。"""
    request = asset.request_data or {}
    expected = asset.expected_result or {}
    return {
        "case_id": str(asset.id),
        "case_name": asset.title,
        "description": asset.description or "",
        "request": request,
        "expected": expected,
        "request_data": request,
        "expected_result": expected,
        "priority": asset.priority or "P2",
        "api_path": request.get("url", "") if isinstance(request, dict) else "",
        "http_method": request.get("method", "") if isinstance(request, dict) else "",
    }


def resolve_revision_case_payload(revision_case: Any, asset: TestCaseAsset | None) -> dict[str, Any]:
    """读取固化载荷；旧修订版只在内容指纹未漂移时兼容补构。"""
    payload = revision_case.case_payload
    if payload is None:
        if asset is None or case_content_hash(asset) != revision_case.content_hash:
            raise ValueError("旧计划修订版的用例内容已变更或被删除，请重新发布计划后执行")
        payload = executable_case_payload(asset)
    if not isinstance(payload, dict) or not isinstance(payload.get("request"), dict):
        raise ValueError("计划修订版用例快照不完整，请重新发布计划后执行")
    result = deepcopy(payload)
    result["case_id"] = str(revision_case.case_asset_id)
    result["case_name"] = revision_case.title
    return result


def cases_from_run_snapshot(
    data: dict[str, Any] | None,
    plan_id: str,
    revision_id: str | None,
    expected_ids: list[str] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """从不可变运行快照为三个执行器分桶，拒绝不完整或不匹配的快照。"""
    if not isinstance(data, dict) or data.get("plan_id") != plan_id:
        raise ValueError("计划运行快照与计划不匹配")
    if data.get("plan_revision_id") != revision_id:
        raise ValueError("计划运行快照与修订版不匹配")
    rows = data.get("cases")
    if not isinstance(rows, list) or not rows:
        raise ValueError("计划运行快照中没有可执行用例")
    if expected_ids is not None and expected_ids != [
        row.get("case_asset_id") if isinstance(row, dict) else None for row in rows
    ]:
        raise ValueError("计划运行快照的用例集合与派发参数不匹配")
    buckets: dict[str, list[dict[str, Any]]] = {
        "api": [], "performance": [], "integration": [],
    }
    for entry in rows:
        if not isinstance(entry, dict) or not isinstance(entry.get("payload"), dict):
            raise ValueError("计划运行快照的用例载荷不完整")
        payload = entry["payload"]
        if payload.get("case_id") != entry.get("case_asset_id"):
            raise ValueError("计划运行快照的用例标识不匹配")
        kind = entry.get("execution_kind") or "api"
        if kind not in buckets:
            raise ValueError(f"不支持的用例执行类型: {kind}")
        buckets[kind].append(deepcopy(payload))
    return buckets
