from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from app.modules.defects.permissions import DefectContext, action_denial
from app.modules.defects.workflow import DEFAULT_WORKFLOW, STATES, action_definition, validate_action_input
from app.schemas.defects import DefectCreate, DefectUpdate, ReferenceInput, TransitionRequest


def test_workflow_all_states_reachable_and_finished_states_reopen():
    edges = {state: set() for state in STATES}
    for action in DEFAULT_WORKFLOW["transitions"]:
        for source in action["from"]:
            edges[source].add(action["to"])
    visited, pending = set(), ["new"]
    while pending:
        current = pending.pop()
        if current in visited:
            continue
        visited.add(current)
        pending.extend(edges[current])
    assert visited == set(STATES)
    assert all("reopened" in edges[state] for state in ("closed", "resolved", "rejected"))


@pytest.mark.parametrize("state", ["new", "unassigned", "in_progress", "pending_verification", "reopened", "rejected"])
def test_unverified_defect_cannot_close(state):
    with pytest.raises(HTTPException) as error:
        action_definition(DEFAULT_WORKFLOW, "close", state)
    assert error.value.status_code == 422


def test_fix_submission_requires_build_note_and_environment_confirmation():
    action = action_definition(DEFAULT_WORKFLOW, "submit_fix", "in_progress")
    current = {"verifier_id": str(uuid4())}
    with pytest.raises(HTTPException):
        validate_action_input(action, current, {"fix_available": True}, "已修复")
    with pytest.raises(HTTPException):
        validate_action_input(action, current, {"fix_build": "build1", "fix_available": False}, "已修复")
    validate_action_input(action, current, {"fix_build": "build1", "fix_available": True}, "已修复")


def test_flow_cannot_smuggle_unrelated_fields():
    action = action_definition(DEFAULT_WORKFLOW, "verify_pass", "pending_verification")
    with pytest.raises(HTTPException):
        validate_action_input(action, {}, {"verified_build": "build1", "assignee_id": str(uuid4())}, "验证通过")


def test_project_role_does_not_grant_write_to_read_only_member():
    user_id = uuid4()
    context = DefectContext(SimpleNamespace(), SimpleNamespace(id=user_id), {"project_manager", "developer"}, False)
    defect = SimpleNamespace(assignee_id=user_id, reporter_id=user_id, verifier_id=user_id)
    assert action_denial(context, defect, action_definition(DEFAULT_WORKFLOW, "start", "unassigned"))


def test_other_developer_cannot_handle_assigned_defect():
    context = DefectContext(SimpleNamespace(), SimpleNamespace(id=uuid4()), {"developer"}, True)
    defect = SimpleNamespace(assignee_id=uuid4(), reporter_id=uuid4(), verifier_id=uuid4())
    assert action_denial(context, defect, action_definition(DEFAULT_WORKFLOW, "submit_fix", "in_progress"))


@pytest.mark.parametrize("payload", [{"title": "  "}, {"description": "  "}, {"source": "pipeline"}, {"workflow_state": "closed"}])
def test_manual_create_cannot_skip_validation_or_impersonate_pipeline(payload):
    with pytest.raises(ValidationError):
        DefectCreate.model_validate({"project_id": str(uuid4()), "title": "普通缺陷", "description": "业务问题", **payload})


def test_nullable_field_update_does_not_clear_required_fields():
    with pytest.raises(ValidationError):
        DefectUpdate.model_validate({"expected_version": 1, "title": None})
    request = DefectUpdate.model_validate({"expected_version": 1, "module_id": None, "labels": []})
    assert request.module_id is None and request.labels == []


def test_reference_requires_exactly_one_matching_target():
    with pytest.raises(ValidationError):
        ReferenceInput.model_validate({"kind": "requirement", "case_asset_id": str(uuid4())})
    with pytest.raises(ValidationError):
        ReferenceInput.model_validate({"kind": "case", "case_asset_id": str(uuid4()), "related_defect_id": str(uuid4())})


def test_reproduction_and_labels_normalize_without_silent_truncation():
    request = DefectCreate(project_id=uuid4(), title="  下单错误  ", description="金额计算错误",
                           reproduce_steps=[" 点击提交 ", ""], labels=["回归", " 回归 ", ""])
    assert request.title == "下单错误"
    assert request.reproduce_steps == ["点击提交"] and request.labels == ["回归"]
    with pytest.raises(ValidationError):
        DefectCreate(project_id=uuid4(), title="金额错误", description="计算异常", labels=["x" * 41])


def test_due_date_requires_timezone():
    with pytest.raises(ValidationError):
        DefectCreate(project_id=uuid4(), title="金额错误", description="计算异常", due_at="2026-10-10T12:00:00")
