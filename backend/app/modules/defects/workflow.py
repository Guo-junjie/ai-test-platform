"""默认流程的声明与校验；配置不能执行任意代码。"""
import hashlib
import json
from copy import deepcopy
from pathlib import Path

from fastapi import HTTPException

_manifest = json.loads(Path(__file__).with_name("default_workflow.json").read_text(encoding="utf-8"))
DEFAULT_WORKFLOW = {key: deepcopy(_manifest[key]) for key in ("schema_version", "name", "revision", "initial_state", "settings", "states", "transitions", "side_actions", "legacy_migration", "rejection_resolutions")}
STATES = {state["key"]: state for state in DEFAULT_WORKFLOW["states"]}
STATE_LABELS = {key: state["label"] for key, state in STATES.items()}
LEGACY_LABELS = {"open": "待处理", "in_fix": "修复中", "verified": "已验证", "closed": "已关闭", "rejected": "已驳回"}
PRIORITY_LABELS = {"urgent": "紧急", "high": "高", "normal": "普通", "low": "低"}
ROLE_KEYS = {"project_manager", "qa_lead", "qa", "developer"}
TRANSITION_FIELDS = {
    "triage": set(), "start": {"assignee_id"}, "resume": {"assignee_id"},
    "submit_fix": {"fix_release_id", "fix_build", "verifier_id", "fix_available"},
    "verify_pass": {"verified_release_id", "verified_build"},
    "verify_fail": {"actual_result"}, "close": set(), "reopen": set(),
    "return_to_queue": {"assignee_id"}, "reject": {"resolution", "duplicate_of_id"},
}


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":")).encode()).hexdigest()


def state_for_legacy(status, resolved=False):
    if not status:
        return "resolved" if resolved else "unassigned"
    return DEFAULT_WORKFLOW["legacy_migration"].get(status, "unassigned")


def action_definition(definition, action_id, state):
    action = next((item for item in definition["transitions"] if item["action_id"] == action_id), None)
    if action is None or action_id not in TRANSITION_FIELDS:
        raise HTTPException(422, "未知的缺陷动作")
    if state not in action["from"]:
        raise HTTPException(422, f"当前状态「{STATE_LABELS.get(state, state)}」不能执行「{action['label']}」")
    return action


def validate_action_input(action, current_fields, supplied, note):
    unexpected = set(supplied) - TRANSITION_FIELDS[action["action_id"]]
    if unexpected:
        raise HTTPException(422, "该动作不允许修改字段：" + "、".join(sorted(unexpected)))
    fields = {**current_fields, **supplied, "note": note}
    missing = [name for name in action.get("required_fields", []) if fields.get(name) in (None, "", False)]
    for alternatives in action.get("required_any", []):
        if not any(fields.get(name) not in (None, "", False) for name in alternatives):
            missing.append(" 或 ".join(alternatives))
    if missing:
        raise HTTPException(422, {"message": "请补齐流转必填内容", "field_errors": missing})
    if action["action_id"] == "submit_fix" and supplied.get("fix_available") is not True:
        raise HTTPException(422, "请确认修复已在被测环境中可验证")


def project_state(defect, definition=DEFAULT_WORKFLOW):
    state = next(item for item in definition["states"] if item["key"] == defect.workflow_state)
    defect.status = state["legacy_status"]
    defect.is_resolved = state["is_resolved"]
