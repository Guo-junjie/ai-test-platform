"""缺陷中心：字段、责任分配、默认工作流、独立历史和稳定检测记录。

DDL 与默认定义在本版本内冻结，不引用可能随以后迭代改变的 ORM 模型。
"""
import hashlib
import json
from uuid import UUID, uuid4, uuid5, NAMESPACE_URL

from alembic import op
import sqlalchemy as sa

revision = "019"
down_revision = "018"

_SCHEMA = json.loads(r'''{
  "core": [
    "\nCREATE TABLE IF NOT EXISTS project_modules (\n\tid UUID NOT NULL, \n\tproject_id UUID NOT NULL, \n\tparent_id UUID, \n\tname VARCHAR(100) NOT NULL, \n\tpath VARCHAR(500) NOT NULL, \n\tis_active BOOLEAN DEFAULT true NOT NULL, \n\tsort_order INTEGER DEFAULT '0' NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now(), \n\tPRIMARY KEY (id), \n\tCONSTRAINT uq_project_module_path UNIQUE (project_id, path), \n\tFOREIGN KEY(project_id) REFERENCES projects (id), \n\tFOREIGN KEY(parent_id) REFERENCES project_modules (id) ON DELETE RESTRICT\n)\n\n",
    "\nCREATE TABLE IF NOT EXISTS project_iterations (\n\tid UUID NOT NULL, \n\tproject_id UUID NOT NULL, \n\tname VARCHAR(100) NOT NULL, \n\tstart_date TIMESTAMP WITH TIME ZONE, \n\tend_date TIMESTAMP WITH TIME ZONE, \n\tstatus VARCHAR(16) DEFAULT 'planned' NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now(), \n\tPRIMARY KEY (id), \n\tCONSTRAINT uq_project_iteration_name UNIQUE (project_id, name), \n\tCONSTRAINT ck_iteration_dates CHECK (end_date IS NULL OR start_date IS NULL OR end_date >= start_date), \n\tFOREIGN KEY(project_id) REFERENCES projects (id)\n)\n\n",
    "\nCREATE TABLE IF NOT EXISTS project_releases (\n\tid UUID NOT NULL, \n\tproject_id UUID NOT NULL, \n\tname VARCHAR(100) NOT NULL, \n\tbuild_ref VARCHAR(200), \n\treleased_at TIMESTAMP WITH TIME ZONE, \n\tstatus VARCHAR(16) DEFAULT 'planned' NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now(), \n\tPRIMARY KEY (id), \n\tCONSTRAINT uq_project_release_name UNIQUE (project_id, name), \n\tFOREIGN KEY(project_id) REFERENCES projects (id)\n)\n\n",
    "\nCREATE TABLE IF NOT EXISTS defect_workflows (\n\tid UUID NOT NULL, \n\tproject_id UUID NOT NULL, \n\tname VARCHAR(100) NOT NULL, \n\tcreated_by UUID, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now(), \n\tPRIMARY KEY (id), \n\tCONSTRAINT uq_defect_workflow_name UNIQUE (project_id, name), \n\tFOREIGN KEY(project_id) REFERENCES projects (id), \n\tFOREIGN KEY(created_by) REFERENCES users (id)\n)\n\n",
    "\nCREATE TABLE IF NOT EXISTS defect_workflow_revisions (\n\tid UUID NOT NULL, \n\tworkflow_id UUID NOT NULL, \n\tproject_id UUID NOT NULL, \n\trevision INTEGER NOT NULL, \n\tstatus VARCHAR(16) NOT NULL, \n\tdefinition_json JSONB NOT NULL, \n\tpublished_by UUID, \n\tpublished_at TIMESTAMP WITH TIME ZONE DEFAULT now(), \n\tPRIMARY KEY (id), \n\tCONSTRAINT uq_defect_workflow_revision UNIQUE (workflow_id, revision), \n\tFOREIGN KEY(workflow_id) REFERENCES defect_workflows (id) ON DELETE RESTRICT, \n\tFOREIGN KEY(project_id) REFERENCES projects (id), \n\tFOREIGN KEY(published_by) REFERENCES users (id)\n)\n\n",
    "\nCREATE TABLE IF NOT EXISTS project_defect_settings (\n\tproject_id UUID NOT NULL, \n\tdefault_workflow_id UUID, \n\tpermission_config JSONB DEFAULT '{}'::jsonb NOT NULL, \n\tfield_config JSONB DEFAULT '{}'::jsonb NOT NULL, \n\tnotification_config JSONB DEFAULT '{}'::jsonb NOT NULL, \n\trow_version INTEGER DEFAULT '1' NOT NULL, \n\tPRIMARY KEY (project_id), \n\tFOREIGN KEY(project_id) REFERENCES projects (id), \n\tFOREIGN KEY(default_workflow_id) REFERENCES defect_workflows (id)\n)\n\n",
    "\nCREATE TABLE IF NOT EXISTS project_defect_role_assignments (\n\tproject_id UUID NOT NULL, \n\tuser_id UUID NOT NULL, \n\trole_key VARCHAR(32) NOT NULL, \n\tPRIMARY KEY (project_id, user_id, role_key), \n\tFOREIGN KEY(project_id) REFERENCES projects (id), \n\tFOREIGN KEY(user_id) REFERENCES users (id)\n)\n\n"
  ],
  "columns": [
    "ALTER TABLE defects ADD COLUMN IF NOT EXISTS defect_key VARCHAR(40) DEFAULT 'BUG-' || nextval('defect_number_seq')::text NOT NULL",
    "ALTER TABLE defects ADD COLUMN IF NOT EXISTS priority VARCHAR(16) DEFAULT 'normal' NOT NULL",
    "ALTER TABLE defects ADD COLUMN IF NOT EXISTS module_id UUID",
    "ALTER TABLE defects ADD COLUMN IF NOT EXISTS iteration_id UUID",
    "ALTER TABLE defects ADD COLUMN IF NOT EXISTS environment_profile_id UUID",
    "ALTER TABLE defects ADD COLUMN IF NOT EXISTS environment_revision_id UUID",
    "ALTER TABLE defects ADD COLUMN IF NOT EXISTS environment_snapshot JSONB DEFAULT '{}'::jsonb NOT NULL",
    "ALTER TABLE defects ADD COLUMN IF NOT EXISTS preconditions TEXT",
    "ALTER TABLE defects ADD COLUMN IF NOT EXISTS expected_result TEXT",
    "ALTER TABLE defects ADD COLUMN IF NOT EXISTS actual_result TEXT",
    "ALTER TABLE defects ADD COLUMN IF NOT EXISTS reproducibility VARCHAR(16) DEFAULT 'unknown' NOT NULL",
    "ALTER TABLE defects ADD COLUMN IF NOT EXISTS reporter_id UUID",
    "ALTER TABLE defects ADD COLUMN IF NOT EXISTS assignee_id UUID",
    "ALTER TABLE defects ADD COLUMN IF NOT EXISTS verifier_id UUID",
    "ALTER TABLE defects ADD COLUMN IF NOT EXISTS fix_submitted_by_id UUID",
    "ALTER TABLE defects ADD COLUMN IF NOT EXISTS resolved_by_id UUID",
    "ALTER TABLE defects ADD COLUMN IF NOT EXISTS closed_by_id UUID",
    "ALTER TABLE defects ADD COLUMN IF NOT EXISTS source VARCHAR(20) DEFAULT 'manual' NOT NULL",
    "ALTER TABLE defects ADD COLUMN IF NOT EXISTS source_metadata JSONB DEFAULT '{}'::jsonb NOT NULL",
    "ALTER TABLE defects ADD COLUMN IF NOT EXISTS workflow_state VARCHAR(64) DEFAULT 'new' NOT NULL",
    "ALTER TABLE defects ADD COLUMN IF NOT EXISTS workflow_revision_id UUID",
    "ALTER TABLE defects ADD COLUMN IF NOT EXISTS proposed_resolution VARCHAR(32)",
    "ALTER TABLE defects ADD COLUMN IF NOT EXISTS resolution VARCHAR(32)",
    "ALTER TABLE defects ADD COLUMN IF NOT EXISTS resolution_note TEXT",
    "ALTER TABLE defects ADD COLUMN IF NOT EXISTS duplicate_of_id UUID",
    "ALTER TABLE defects ADD COLUMN IF NOT EXISTS fix_release_id UUID",
    "ALTER TABLE defects ADD COLUMN IF NOT EXISTS verified_release_id UUID",
    "ALTER TABLE defects ADD COLUMN IF NOT EXISTS fix_build VARCHAR(200)",
    "ALTER TABLE defects ADD COLUMN IF NOT EXISTS verified_build VARCHAR(200)",
    "ALTER TABLE defects ADD COLUMN IF NOT EXISTS labels JSONB DEFAULT '[]'::jsonb NOT NULL",
    "ALTER TABLE defects ADD COLUMN IF NOT EXISTS due_at TIMESTAMP WITH TIME ZONE",
    "ALTER TABLE defects ADD COLUMN IF NOT EXISTS assigned_at TIMESTAMP WITH TIME ZONE",
    "ALTER TABLE defects ADD COLUMN IF NOT EXISTS started_at TIMESTAMP WITH TIME ZONE",
    "ALTER TABLE defects ADD COLUMN IF NOT EXISTS fix_submitted_at TIMESTAMP WITH TIME ZONE",
    "ALTER TABLE defects ADD COLUMN IF NOT EXISTS resolved_at TIMESTAMP WITH TIME ZONE",
    "ALTER TABLE defects ADD COLUMN IF NOT EXISTS closed_at TIMESTAMP WITH TIME ZONE",
    "ALTER TABLE defects ADD COLUMN IF NOT EXISTS first_resolved_at TIMESTAMP WITH TIME ZONE",
    "ALTER TABLE defects ADD COLUMN IF NOT EXISTS reopened_count INTEGER DEFAULT '0' NOT NULL",
    "ALTER TABLE defects ADD COLUMN IF NOT EXISTS row_version INTEGER DEFAULT '1' NOT NULL",
    "ALTER TABLE defects ADD COLUMN IF NOT EXISTS event_sequence INTEGER DEFAULT '0' NOT NULL",
    "ALTER TABLE defects ADD COLUMN IF NOT EXISTS creation_request_id UUID",
    "ALTER TABLE defects ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE DEFAULT now()",
    "ALTER TABLE defects ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP WITH TIME ZONE",
    "ALTER TABLE defects ADD COLUMN IF NOT EXISTS deleted_by UUID"
  ],
  "constraints": [
    {
      "name": "fk_defects_closed_by_id",
      "sql": "ALTER TABLE defects ADD CONSTRAINT fk_defects_closed_by_id FOREIGN KEY(closed_by_id) REFERENCES users (id)"
    },
    {
      "name": "fk_defects_iteration_id",
      "sql": "ALTER TABLE defects ADD CONSTRAINT fk_defects_iteration_id FOREIGN KEY(iteration_id) REFERENCES project_iterations (id) ON DELETE RESTRICT"
    },
    {
      "name": "fk_defects_environment_profile_id",
      "sql": "ALTER TABLE defects ADD CONSTRAINT fk_defects_environment_profile_id FOREIGN KEY(environment_profile_id) REFERENCES environment_profiles (id)"
    },
    {
      "name": "fk_defects_workflow_revision_id",
      "sql": "ALTER TABLE defects ADD CONSTRAINT fk_defects_workflow_revision_id FOREIGN KEY(workflow_revision_id) REFERENCES defect_workflow_revisions (id)"
    },
    {
      "name": "fk_defects_environment_revision_id",
      "sql": "ALTER TABLE defects ADD CONSTRAINT fk_defects_environment_revision_id FOREIGN KEY(environment_revision_id) REFERENCES environment_profile_revisions (id)"
    },
    {
      "name": "fk_defects_project_id",
      "sql": "ALTER TABLE defects ADD CONSTRAINT fk_defects_project_id FOREIGN KEY(project_id) REFERENCES projects (id)"
    },
    {
      "name": "fk_defects_duplicate_of_id",
      "sql": "ALTER TABLE defects ADD CONSTRAINT fk_defects_duplicate_of_id FOREIGN KEY(duplicate_of_id) REFERENCES defects (id) ON DELETE RESTRICT"
    },
    {
      "name": "fk_defects_reporter_id",
      "sql": "ALTER TABLE defects ADD CONSTRAINT fk_defects_reporter_id FOREIGN KEY(reporter_id) REFERENCES users (id)"
    },
    {
      "name": "fk_defects_fix_release_id",
      "sql": "ALTER TABLE defects ADD CONSTRAINT fk_defects_fix_release_id FOREIGN KEY(fix_release_id) REFERENCES project_releases (id)"
    },
    {
      "name": "fk_defects_assignee_id",
      "sql": "ALTER TABLE defects ADD CONSTRAINT fk_defects_assignee_id FOREIGN KEY(assignee_id) REFERENCES users (id)"
    },
    {
      "name": "fk_defects_verified_release_id",
      "sql": "ALTER TABLE defects ADD CONSTRAINT fk_defects_verified_release_id FOREIGN KEY(verified_release_id) REFERENCES project_releases (id)"
    },
    {
      "name": "fk_defects_verifier_id",
      "sql": "ALTER TABLE defects ADD CONSTRAINT fk_defects_verifier_id FOREIGN KEY(verifier_id) REFERENCES users (id)"
    },
    {
      "name": "fk_defects_deleted_by",
      "sql": "ALTER TABLE defects ADD CONSTRAINT fk_defects_deleted_by FOREIGN KEY(deleted_by) REFERENCES users (id)"
    },
    {
      "name": "uq_defect_creation_request",
      "sql": "ALTER TABLE defects ADD CONSTRAINT uq_defect_creation_request UNIQUE (project_id, reporter_id, creation_request_id)"
    },
    {
      "name": "fk_defects_fix_submitted_by_id",
      "sql": "ALTER TABLE defects ADD CONSTRAINT fk_defects_fix_submitted_by_id FOREIGN KEY(fix_submitted_by_id) REFERENCES users (id)"
    },
    {
      "name": "uq_defect_id_project",
      "sql": "ALTER TABLE defects ADD CONSTRAINT uq_defect_id_project UNIQUE (id, project_id)"
    },
    {
      "name": "fk_defects_module_id",
      "sql": "ALTER TABLE defects ADD CONSTRAINT fk_defects_module_id FOREIGN KEY(module_id) REFERENCES project_modules (id) ON DELETE RESTRICT"
    },
    {
      "name": "uq_defects_defect_key",
      "sql": "ALTER TABLE defects ADD CONSTRAINT uq_defects_defect_key UNIQUE (defect_key)"
    },
    {
      "name": "fk_defects_resolved_by_id",
      "sql": "ALTER TABLE defects ADD CONSTRAINT fk_defects_resolved_by_id FOREIGN KEY(resolved_by_id) REFERENCES users (id)"
    }
  ],
  "children": [
    "\nCREATE TABLE IF NOT EXISTS defect_affected_releases (\n\tid UUID NOT NULL, \n\tdefect_id UUID NOT NULL, \n\tproject_id UUID NOT NULL, \n\trelease_id UUID NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(defect_id, project_id) REFERENCES defects (id, project_id) ON DELETE RESTRICT, \n\tCONSTRAINT uq_defect_affected_release UNIQUE (defect_id, release_id), \n\tFOREIGN KEY(project_id) REFERENCES projects (id), \n\tFOREIGN KEY(release_id) REFERENCES project_releases (id)\n)\n\n",
    "\nCREATE TABLE IF NOT EXISTS defect_references (\n\tid UUID NOT NULL, \n\tdefect_id UUID NOT NULL, \n\tproject_id UUID NOT NULL, \n\tkind VARCHAR(16) NOT NULL, \n\trequirement_doc_id UUID, \n\trequirement_item_key VARCHAR(200), \n\tcase_asset_id UUID, \n\trelated_defect_id UUID, \n\trelation VARCHAR(16) NOT NULL, \n\ttitle_snapshot VARCHAR(500), \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now(), \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(defect_id, project_id) REFERENCES defects (id, project_id) ON DELETE RESTRICT, \n\tCONSTRAINT ck_defect_reference_target CHECK ((kind='requirement' AND requirement_doc_id IS NOT NULL AND case_asset_id IS NULL AND related_defect_id IS NULL) OR (kind='case' AND requirement_doc_id IS NULL AND case_asset_id IS NOT NULL AND related_defect_id IS NULL) OR (kind='defect' AND requirement_doc_id IS NULL AND case_asset_id IS NULL AND related_defect_id IS NOT NULL)), \n\tFOREIGN KEY(project_id) REFERENCES projects (id), \n\tFOREIGN KEY(requirement_doc_id) REFERENCES requirement_docs (id), \n\tFOREIGN KEY(case_asset_id) REFERENCES test_case_assets (id), \n\tFOREIGN KEY(related_defect_id) REFERENCES defects (id)\n)\n\n",
    "\nCREATE TABLE IF NOT EXISTS defect_events (\n\tid UUID NOT NULL, \n\tdefect_id UUID NOT NULL, \n\tproject_id UUID NOT NULL, \n\tsequence INTEGER NOT NULL, \n\tevent_type VARCHAR(40) NOT NULL, \n\tactor_id UUID, \n\tactor_kind VARCHAR(16) NOT NULL, \n\tfrom_state VARCHAR(64), \n\tto_state VARCHAR(64), \n\tchanges_json JSONB NOT NULL, \n\tnote TEXT, \n\trequest_id UUID, \n\trequest_hash VARCHAR(64), \n\tresult_json JSONB NOT NULL, \n\tis_legacy BOOLEAN DEFAULT false NOT NULL, \n\toccurred_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(defect_id, project_id) REFERENCES defects (id, project_id) ON DELETE RESTRICT, \n\tCONSTRAINT uq_defect_event_sequence UNIQUE (defect_id, sequence), \n\tCONSTRAINT uq_defect_event_request UNIQUE (defect_id, request_id), \n\tFOREIGN KEY(project_id) REFERENCES projects (id), \n\tFOREIGN KEY(actor_id) REFERENCES users (id)\n)\n\n",
    "\nCREATE TABLE IF NOT EXISTS defect_occurrences (\n\tid UUID NOT NULL, \n\tdefect_id UUID NOT NULL, \n\tproject_id UUID NOT NULL, \n\ttest_run_id UUID NOT NULL, \n\ttest_case_id UUID, \n\ttest_result_id UUID, \n\tcase_asset_id UUID, \n\tsignature VARCHAR(64) NOT NULL, \n\tsignature_version INTEGER NOT NULL, \n\tobserved_at TIMESTAMP WITH TIME ZONE DEFAULT now(), \n\tevidence_json JSONB NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(defect_id, project_id) REFERENCES defects (id, project_id) ON DELETE RESTRICT, \n\tCONSTRAINT uq_defect_occurrence_signature UNIQUE (test_run_id, signature_version, signature), \n\tFOREIGN KEY(project_id) REFERENCES projects (id), \n\tFOREIGN KEY(test_run_id) REFERENCES test_runs (id), \n\tFOREIGN KEY(test_case_id) REFERENCES test_cases (id), \n\tFOREIGN KEY(test_result_id) REFERENCES test_results (id), \n\tFOREIGN KEY(case_asset_id) REFERENCES test_case_assets (id)\n)\n\n"
  ],
  "indexes": [
    "CREATE INDEX IF NOT EXISTS ix_project_modules_project_id ON project_modules (project_id)",
    "CREATE INDEX IF NOT EXISTS ix_project_iterations_project_id ON project_iterations (project_id)",
    "CREATE INDEX IF NOT EXISTS ix_project_releases_project_id ON project_releases (project_id)",
    "CREATE INDEX IF NOT EXISTS ix_defect_workflows_project_id ON defect_workflows (project_id)",
    "CREATE INDEX IF NOT EXISTS ix_defect_workflow_revisions_project_id ON defect_workflow_revisions (project_id)",
    "CREATE INDEX IF NOT EXISTS ix_defect_affected_releases_project_id ON defect_affected_releases (project_id)",
    "CREATE INDEX IF NOT EXISTS ix_defect_references_project_id ON defect_references (project_id)",
    "CREATE INDEX IF NOT EXISTS idx_defect_events_project_time ON defect_events (project_id, occurred_at, event_type)",
    "CREATE INDEX IF NOT EXISTS ix_defect_events_defect_id ON defect_events (defect_id)",
    "CREATE INDEX IF NOT EXISTS ix_defect_events_project_id ON defect_events (project_id)",
    "CREATE INDEX IF NOT EXISTS ix_defect_occurrences_project_id ON defect_occurrences (project_id)",
    "CREATE INDEX IF NOT EXISTS ix_defect_occurrences_defect_id ON defect_occurrences (defect_id)",
    "CREATE INDEX IF NOT EXISTS idx_defects_project_state_updated ON defects (project_id, workflow_state, updated_at)",
    "CREATE INDEX IF NOT EXISTS idx_defects_labels ON defects USING gin (labels)",
    "CREATE INDEX IF NOT EXISTS idx_defects_project_assignee ON defects (project_id, assignee_id, workflow_state)"
  ]
}''')
_WORKFLOW = json.loads(r'''{
  "schema_version": 1,
  "name": "默认缺陷协作流程",
  "revision": 1,
  "initial_state": "new",
  "settings": {
    "require_expected_version": true,
    "require_request_id": true,
    "allow_self_verification": false,
    "allow_direct_close": false,
    "privileged_override_requires_note": true
  },
  "states": [
    {
      "key": "new",
      "label": "新建",
      "category": "todo",
      "legacy_status": "open",
      "is_resolved": false,
      "is_backlog": true
    },
    {
      "key": "unassigned",
      "label": "待分配",
      "category": "todo",
      "legacy_status": "open",
      "is_resolved": false,
      "is_backlog": true
    },
    {
      "key": "in_progress",
      "label": "处理中",
      "category": "in_progress",
      "legacy_status": "in_fix",
      "is_resolved": false,
      "is_backlog": true
    },
    {
      "key": "pending_verification",
      "label": "待验证",
      "category": "verification",
      "legacy_status": "in_fix",
      "is_resolved": false,
      "is_backlog": true
    },
    {
      "key": "resolved",
      "label": "已解决",
      "category": "done_verified",
      "legacy_status": "verified",
      "is_resolved": true,
      "is_backlog": false
    },
    {
      "key": "closed",
      "label": "已关闭",
      "category": "done_verified",
      "legacy_status": "closed",
      "is_resolved": true,
      "is_backlog": false
    },
    {
      "key": "reopened",
      "label": "重开",
      "category": "todo",
      "legacy_status": "open",
      "is_resolved": false,
      "is_backlog": true
    },
    {
      "key": "rejected",
      "label": "拒绝",
      "category": "done_rejected",
      "legacy_status": "rejected",
      "is_resolved": false,
      "is_backlog": false
    }
  ],
  "transitions": [
    {
      "action_id": "triage",
      "label": "完成分诊",
      "from": [
        "new"
      ],
      "to": "unassigned",
      "permission": "defect.assign",
      "roles": [
        "project_manager",
        "qa_lead"
      ],
      "actor_relations": [
        "project_manager",
        "qa_lead"
      ],
      "required_fields": [
        "title",
        "description",
        "severity",
        "priority"
      ],
      "validators": [
        "project_required_fields"
      ],
      "effects": []
    },
    {
      "action_id": "start",
      "label": "接受处理",
      "from": [
        "unassigned"
      ],
      "to": "in_progress",
      "permission": "defect.start",
      "roles": [
        "developer",
        "project_manager",
        "qa_lead"
      ],
      "actor_relations": [
        "assignee",
        "privileged_override"
      ],
      "required_fields": [
        "assignee_id"
      ],
      "validators": [
        "active_project_assignee",
        "privileged_override_note"
      ],
      "effects": [
        "set_started_at_if_missing"
      ]
    },
    {
      "action_id": "submit_fix",
      "label": "提交修复",
      "from": [
        "in_progress"
      ],
      "to": "pending_verification",
      "permission": "defect.submit_fix",
      "roles": [
        "developer",
        "project_manager",
        "qa_lead"
      ],
      "actor_relations": [
        "assignee",
        "privileged_override"
      ],
      "required_fields": [
        "note",
        "verifier_id",
        "fix_available"
      ],
      "required_any": [
        [
          "fix_release_id",
          "fix_build"
        ]
      ],
      "validators": [
        "active_project_verifier",
        "same_project_release",
        "fix_available_true",
        "self_verification_policy",
        "privileged_override_note"
      ],
      "effects": [
        "set_fix_submitted_at",
        "set_proposed_resolution_fixed"
      ]
    },
    {
      "action_id": "verify_pass",
      "label": "验证通过",
      "from": [
        "pending_verification"
      ],
      "to": "resolved",
      "permission": "defect.verify",
      "roles": [
        "qa",
        "qa_lead",
        "project_manager"
      ],
      "actor_relations": [
        "verifier",
        "privileged_override"
      ],
      "required_fields": [
        "note"
      ],
      "required_any": [
        [
          "verified_release_id",
          "verified_build"
        ]
      ],
      "validators": [
        "same_project_release",
        "self_verification_policy",
        "privileged_override_note"
      ],
      "effects": [
        "set_resolution_fixed",
        "set_resolved_at",
        "set_first_resolved_at_if_missing"
      ]
    },
    {
      "action_id": "verify_fail",
      "label": "验证失败",
      "from": [
        "pending_verification"
      ],
      "to": "reopened",
      "permission": "defect.verify",
      "roles": [
        "qa",
        "qa_lead",
        "project_manager"
      ],
      "actor_relations": [
        "verifier",
        "privileged_override"
      ],
      "required_fields": [
        "note",
        "actual_result"
      ],
      "validators": [
        "self_verification_policy",
        "privileged_override_note"
      ],
      "effects": [
        "snapshot_current_cycle",
        "clear_current_cycle",
        "increment_reopened_count"
      ]
    },
    {
      "action_id": "close",
      "label": "关闭",
      "from": [
        "resolved"
      ],
      "to": "closed",
      "permission": "defect.close",
      "roles": [
        "qa",
        "qa_lead",
        "project_manager"
      ],
      "actor_relations": [
        "verifier",
        "qa_lead",
        "project_manager"
      ],
      "required_fields": [],
      "validators": [
        "verified_resolution"
      ],
      "effects": [
        "set_closed_at"
      ]
    },
    {
      "action_id": "reopen",
      "label": "重开",
      "from": [
        "resolved",
        "closed",
        "rejected"
      ],
      "to": "reopened",
      "permission": "defect.reopen",
      "roles": [
        "qa",
        "developer",
        "qa_lead",
        "project_manager"
      ],
      "actor_relations": [
        "reporter",
        "verifier",
        "qa_lead",
        "project_manager"
      ],
      "required_fields": [
        "note"
      ],
      "validators": [],
      "effects": [
        "snapshot_current_cycle",
        "clear_current_cycle",
        "increment_reopened_count"
      ]
    },
    {
      "action_id": "resume",
      "label": "继续处理",
      "from": [
        "reopened"
      ],
      "to": "in_progress",
      "permission": "defect.start",
      "roles": [
        "developer",
        "project_manager",
        "qa_lead"
      ],
      "actor_relations": [
        "assignee",
        "privileged_override"
      ],
      "required_fields": [
        "assignee_id"
      ],
      "validators": [
        "active_project_assignee",
        "privileged_override_note"
      ],
      "effects": [
        "set_started_at_if_missing"
      ]
    },
    {
      "action_id": "return_to_queue",
      "label": "退回待分配",
      "from": [
        "in_progress",
        "reopened"
      ],
      "to": "unassigned",
      "permission": "defect.return_to_queue",
      "roles": [
        "developer",
        "qa_lead",
        "project_manager"
      ],
      "actor_relations": [
        "assignee",
        "qa_lead",
        "project_manager"
      ],
      "required_fields": [
        "note"
      ],
      "validators": [],
      "effects": [
        "snapshot_current_cycle",
        "clear_started_at"
      ]
    },
    {
      "action_id": "reject",
      "label": "拒绝",
      "from": [
        "new",
        "unassigned",
        "in_progress",
        "reopened"
      ],
      "to": "rejected",
      "permission": "defect.reject",
      "roles": [
        "project_manager",
        "qa_lead"
      ],
      "actor_relations": [
        "project_manager",
        "qa_lead"
      ],
      "required_fields": [
        "note",
        "resolution"
      ],
      "validators": [
        "rejection_resolution",
        "duplicate_target_if_required"
      ],
      "effects": [
        "set_rejection_resolution",
        "set_resolution_note"
      ]
    }
  ],
  "side_actions": [
    {
      "action_id": "assign",
      "label": "指派或转派",
      "allowed_states": [
        "new",
        "unassigned",
        "in_progress",
        "pending_verification",
        "reopened"
      ],
      "permission": "defect.assign",
      "roles": [
        "project_manager",
        "qa_lead"
      ],
      "required_fields": [
        "assignee_id"
      ],
      "validators": [
        "active_project_assignee",
        "active_project_verifier_if_set",
        "reassignment_note_if_required"
      ],
      "effects": [
        "set_assigned_at"
      ],
      "changes_state": false
    }
  ],
  "legacy_migration": {
    "open": "unassigned",
    "in_fix": "in_progress",
    "verified": "resolved",
    "closed": "closed",
    "rejected": "rejected"
  },
  "rejection_resolutions": [
    "duplicate",
    "not_a_bug",
    "wont_fix",
    "cannot_reproduce"
  ]
}''')


def upgrade():
    bind = op.get_bind()
    unknown = bind.execute(sa.text("SELECT count(*) FROM defects WHERE status IS NOT NULL AND status NOT IN ('open','in_fix','verified','closed','rejected')")).scalar()
    if unknown:
        raise RuntimeError("发现未知的历史缺陷状态，请先核对，迁移未修改数据库。")
    bind.execute(sa.text("CREATE SEQUENCE IF NOT EXISTS defect_number_seq"))
    for sql in _SCHEMA["core"] + _SCHEMA["columns"]:
        bind.execute(sa.text(sql))
    # 只依据有外键保障的任务归属回填；无法归属的旧数据仍留给管理员处理。
    bind.execute(sa.text("UPDATE defects d SET project_id=r.project_id FROM test_runs r WHERE d.project_id IS NULL AND d.test_run_id=r.id"))
    for constraint in _SCHEMA["constraints"]:
        exists = bind.execute(sa.text("SELECT 1 FROM pg_constraint WHERE conrelid='defects'::regclass AND conname=:name"), {"name": constraint["name"]}).scalar()
        if not exists:
            bind.execute(sa.text(constraint["sql"]))
    if not bind.execute(sa.text("SELECT 1 FROM pg_constraint WHERE conrelid='defects'::regclass AND conname='ck_defect_priority'" )).scalar():
        bind.execute(sa.text("ALTER TABLE defects ADD CONSTRAINT ck_defect_priority CHECK (priority IN ('urgent','high','normal','low'))"))
    for sql in _SCHEMA["children"] + _SCHEMA["indexes"]:
        bind.execute(sa.text(sql))
    # 不分离疑似备注、不猜测用户和过程时间。把旧状态及原始证据留在迁移快照中。
    bind.execute(sa.text("""UPDATE defects SET
        source_metadata=jsonb_build_object('legacy_snapshot', jsonb_build_object(
            'status',status,'is_resolved',is_resolved,'title',title,'description',description,
            'reproduce_steps',reproduce_steps,'created_at',created_at)),
        source=CASE WHEN test_run_id IS NOT NULL THEN 'pipeline' ELSE 'manual' END,
        workflow_state=CASE status WHEN 'open' THEN 'unassigned' WHEN 'in_fix' THEN 'in_progress'
            WHEN 'verified' THEN 'resolved' WHEN 'closed' THEN 'closed' WHEN 'rejected' THEN 'rejected'
            ELSE CASE WHEN is_resolved THEN 'resolved' ELSE 'unassigned' END END,
        resolution=CASE WHEN status IN ('verified','closed','rejected') OR (status IS NULL AND is_resolved)
            THEN 'legacy_unknown' ELSE NULL END,
        updated_at=created_at AT TIME ZONE 'UTC'
        WHERE event_sequence=0"""))
    bind.execute(sa.text("""UPDATE defects SET status=CASE workflow_state WHEN 'resolved' THEN 'verified'
        WHEN 'closed' THEN 'closed' WHEN 'rejected' THEN 'rejected' WHEN 'in_progress' THEN 'in_fix'
        ELSE 'open' END, is_resolved=workflow_state IN ('resolved','closed') WHERE event_sequence=0"""))
    for project in bind.execute(sa.text("SELECT id,owner_id FROM projects")).mappings():
        workflow_id = uuid5(NAMESPACE_URL, "aitp:defect:workflow:" + str(project["id"]))
        revision_id = uuid5(NAMESPACE_URL, "aitp:defect:revision1:" + str(project["id"]))
        params = {"wid": workflow_id, "rid": revision_id, "pid": project["id"], "owner": project["owner_id"],
                  "definition": json.dumps(_WORKFLOW, ensure_ascii=False)}
        bind.execute(sa.text("INSERT INTO defect_workflows (id,project_id,name,created_by) VALUES (:wid,:pid,'默认缺陷协作流程',:owner) ON CONFLICT DO NOTHING"), params)
        bind.execute(sa.text("INSERT INTO defect_workflow_revisions (id,workflow_id,project_id,revision,status,definition_json) VALUES (:rid,:wid,:pid,1,'published',CAST(:definition AS jsonb)) ON CONFLICT DO NOTHING"), params)
        bind.execute(sa.text("INSERT INTO project_defect_settings (project_id,default_workflow_id) VALUES (:pid,:wid) ON CONFLICT DO NOTHING"), params)
        bind.execute(sa.text("UPDATE defects SET workflow_revision_id=:rid WHERE project_id=:pid AND workflow_revision_id IS NULL"), params)
    for defect in bind.execute(sa.text("SELECT id,project_id,workflow_state,source_metadata FROM defects WHERE project_id IS NOT NULL AND event_sequence=0")).mappings():
        bind.execute(sa.text("""INSERT INTO defect_events
            (id,defect_id,project_id,sequence,event_type,actor_kind,to_state,changes_json,result_json,is_legacy)
            VALUES (:id,:did,:pid,1,'legacy_imported','system',:state,CAST(:changes AS jsonb),'{}'::jsonb,true)"""),
            {"id": uuid4(), "did": defect["id"], "pid": defect["project_id"], "state": defect["workflow_state"],
             "changes": json.dumps(defect["source_metadata"], default=str, ensure_ascii=False)})
        bind.execute(sa.text("UPDATE defects SET event_sequence=1 WHERE id=:id"), {"id": defect["id"]})
    # 旧缺陷仅在有真实执行用例时建立稳定映射；重复旧记录不删除，优先保留已处理记录。
    for defect in bind.execute(sa.text("""SELECT d.id,d.project_id,d.test_run_id,d.test_case_id,c.case_asset_id
        FROM defects d JOIN test_cases c ON c.id=d.test_case_id AND c.test_run_id=d.test_run_id
        WHERE d.project_id IS NOT NULL
        ORDER BY CASE WHEN d.status='open' THEN 1 ELSE 0 END, d.created_at,d.id""")).mappings():
        signature = hashlib.sha256(("case:" + str(defect["test_case_id"])).encode()).hexdigest()
        bind.execute(sa.text("""INSERT INTO defect_occurrences
            (id,defect_id,project_id,test_run_id,test_case_id,case_asset_id,signature,signature_version,evidence_json)
            VALUES (:id,:did,:pid,:rid,:cid,:asset,:signature,1,'{"legacy": true}'::jsonb)
            ON CONFLICT (test_run_id,signature_version,signature) DO NOTHING"""),
            {"id": uuid4(), "did": defect["id"], "pid": defect["project_id"], "rid": defect["test_run_id"],
             "cid": defect["test_case_id"], "asset": defect["case_asset_id"], "signature": signature})


def downgrade():
    # 新状态的历史不能无损降回五状态，不提供会丢协作数据的自动降级。
    raise RuntimeError("019 包含不可丢弃的缺陷历史。请停写后恢复迁移前备份，或部署兼容版本回退 UI。")
